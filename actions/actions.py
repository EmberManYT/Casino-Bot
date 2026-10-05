from __future__ import annotations

import re
from typing import Any

from rasa_sdk import Action, Tracker
from rasa_sdk.events import EventType, SlotSet
from rasa_sdk.executor import CollectingDispatcher


CARD_VALUES = {
    "ace": 11, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9, "10": 10, "jack": 10, "queen": 10, "king": 10,
}
CARD_ALIASES = {
    "one": "ace", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}
CARD_PATTERN = re.compile(
    r"(?<![a-z0-9])(ace|[2-9]|10|jack|queen|king|one|two|three|four|five|six|seven|eight|nine|ten)(?![a-z0-9])",
    re.IGNORECASE,
)


def extract_cards(text: str) -> list[str]:
    cards = [match.group(1).lower() for match in CARD_PATTERN.finditer(text)]
    return [CARD_ALIASES.get(card, card) for card in cards]


def score_hand(cards: list[str]) -> tuple[int, bool]:
    total = sum(CARD_VALUES[card] for card in cards)
    aces_as_eleven = cards.count("ace")
    while total > 21 and aces_as_eleven:
        total -= 10
        aces_as_eleven -= 1
    return total, aces_as_eleven > 0


def basic_hit_or_stand(total: int, soft: bool, dealer: str) -> str:
    dealer_total = CARD_VALUES[dealer]
    if total >= 21:
        return "stand"
    if soft:
        if total <= 17:
            return "hit"
        if total == 18:
            return "stand" if dealer_total in {2, 3, 4, 5, 6, 7, 8} else "hit"
        return "stand"
    if total <= 11:
        return "hit"
    if total == 12:
        return "stand" if dealer_total in {4, 5, 6} else "hit"
    if 13 <= total <= 16:
        return "stand" if dealer_total in {2, 3, 4, 5, 6} else "hit"
    return "stand"


class StartBlackjack(Action):
    def name(self) -> str:
        return "action_start_blackjack"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict[str, Any]) -> list[EventType]:
        return [
            SlotSet("user_input", None), SlotSet("input_valid", False),
            SlotSet("player_hand", []), SlotSet("dealer_upcard", None),
            SlotSet("player_move", None), SlotSet("hand_value", 0),
            SlotSet("is_soft_hand", False), SlotSet("game_status", "collecting"),
            SlotSet("recommendation", None),
        ]


class RecordInitialHand(Action):
    def name(self) -> str:
        return "action_record_initial_hand"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict[str, Any]) -> list[EventType]:
        cards = extract_cards(tracker.get_slot("user_input") or "")
        if len(cards) != 2:
            dispatcher.utter_message(response="utter_invalid_initial_hand")
            return [SlotSet("input_valid", False)]
        return [SlotSet("player_hand", cards), SlotSet("input_valid", True)]


class RecordDealerCard(Action):
    def name(self) -> str:
        return "action_record_dealer_card"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict[str, Any]) -> list[EventType]:
        cards = extract_cards(tracker.get_slot("user_input") or "")
        if len(cards) != 1:
            dispatcher.utter_message(response="utter_invalid_dealer_card")
            return [SlotSet("input_valid", False)]
        return [SlotSet("dealer_upcard", cards[0]), SlotSet("input_valid", True)]


class EvaluateBlackjack(Action):
    def name(self) -> str:
        return "action_evaluate_blackjack"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict[str, Any]) -> list[EventType]:
        cards = tracker.get_slot("player_hand") or []
        total, soft = score_hand(cards)
        if total > 21:
            dispatcher.utter_message(text=f"You have {total}. Bust.")
            return [SlotSet("hand_value", total), SlotSet("is_soft_hand", soft), SlotSet("game_status", "bust")]
        if total == 21 and len(cards) == 2:
            dispatcher.utter_message(text="Blackjack — 21 with your first two cards.")
            return [SlotSet("hand_value", total), SlotSet("is_soft_hand", soft), SlotSet("game_status", "blackjack")]
        dealer = tracker.get_slot("dealer_upcard")
        advice = basic_hit_or_stand(total, soft, dealer)
        kind = "soft" if soft else "hard"
        dispatcher.utter_message(text=f"You have a {kind} {total} against the dealer's {dealer}. Basic strategy says: {advice.upper()}.")
        return [SlotSet("hand_value", total), SlotSet("is_soft_hand", soft), SlotSet("game_status", "active"), SlotSet("recommendation", advice)]


class RecordNextCard(Action):
    def name(self) -> str:
        return "action_record_next_card"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict[str, Any]) -> list[EventType]:
        cards = extract_cards(tracker.get_slot("user_input") or "")
        if len(cards) != 1:
            dispatcher.utter_message(response="utter_invalid_next_card")
            return [SlotSet("input_valid", False)]
        hand = list(tracker.get_slot("player_hand") or [])
        hand.append(cards[0])
        return [SlotSet("player_hand", hand), SlotSet("input_valid", True), SlotSet("player_move", None)]


class StandBlackjack(Action):
    def name(self) -> str:
        return "action_stand_blackjack"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: dict[str, Any]) -> list[EventType]:
        total = tracker.get_slot("hand_value")
        dispatcher.utter_message(text=f"You stand on {total}.")
        return [SlotSet("game_status", "stood")]
