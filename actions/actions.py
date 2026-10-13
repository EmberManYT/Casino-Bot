from __future__ import annotations

import re
from typing import Any

import requests
from rasa_sdk import Action, Tracker
from rasa_sdk.events import EventType, SlotSet
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.forms import ValidationAction


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
DECK_API = "https://deckofcardsapi.com/api/deck"
DEFAULT_DECK_COUNT = 6


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


def parse_money(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d{1,2})?", str(value or "").replace(",", ""))
    return float(match.group()) if match else None


def api_rank(card: dict[str, Any]) -> str:
    value = str(card["value"]).lower()
    return "ace" if value == "ace" else value


def card_name(card: dict[str, Any]) -> str:
    return f"{str(card['value']).title()} of {str(card['suit']).title()}"


def api_hand_score(cards: list[dict[str, Any]]) -> tuple[int, bool]:
    return score_hand([api_rank(card) for card in cards])


def deck_request(path: str, **params: Any) -> dict[str, Any]:
    response = requests.get(f"{DECK_API}/{path}", params=params, timeout=10)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise ValueError("Deck of Cards API returned an unsuccessful response")
    return payload


def draw_cards(deck_id: str, count: int) -> tuple[list[dict[str, Any]], int]:
    payload = deck_request(f"{deck_id}/draw/", count=count)
    cards = payload.get("cards", [])
    if len(cards) != count:
        raise ValueError("Deck of Cards API returned too few cards")
    return cards, int(payload["remaining"])


def settle_round(
    dispatcher: CollectingDispatcher,
    balance: float,
    bet: float,
    result: str,
) -> list[EventType]:
    if result == "win":
        balance += bet * 2
        message = f"You win ${bet * 2:.2f}. Your balance is ${balance:.2f}."
    elif result == "push":
        balance += bet
        message = f"Push—your ${bet:.2f} bet is returned. Your balance is ${balance:.2f}."
    else:
        message = f"Dealer wins. Your balance is ${balance:.2f}."

    dispatcher.utter_message(text=message)
    if balance <= 0:
        dispatcher.utter_message(text="Your balance is $0.00, so the practice session is over.")
        status = "session_complete"
    else:
        status = "round_complete"
    return [
        SlotSet("practice_balance", balance),
        SlotSet("practice_status", status),
        SlotSet("round_result", result),
        SlotSet("player_move", None),
    ]


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


class ValidatePracticeBlackjack(ValidationAction):
    async def validate_starting_balance(
        self, value: Any, dispatcher: CollectingDispatcher,
        tracker: Tracker, domain: dict[str, Any],
    ) -> dict[str, Any]:
        balance = parse_money(value)
        if balance is None or balance <= 0:
            dispatcher.utter_message(text="Enter a starting balance greater than $0.")
            return {"starting_balance": None}
        return {"starting_balance": balance}

    async def validate_practice_bet(
        self, value: Any, dispatcher: CollectingDispatcher,
        tracker: Tracker, domain: dict[str, Any],
    ) -> dict[str, Any]:
        bet = parse_money(value)
        balance = float(tracker.get_slot("practice_balance") or 0)
        if bet is None or bet <= 0:
            dispatcher.utter_message(text="Your bet must be greater than $0.")
            return {"practice_bet": None}
        if bet > balance:
            dispatcher.utter_message(
                text=f"That bet is higher than your ${balance:.2f} balance. Choose a smaller bet."
            )
            return {"practice_bet": None}
        return {"practice_bet": bet}


class StartPracticeBlackjack(Action):
    def name(self) -> str:
        return "action_start_practice_blackjack"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker,
            domain: dict[str, Any]) -> list[EventType]:
        balance = parse_money(tracker.get_slot("starting_balance"))
        if balance is None or balance <= 0:
            dispatcher.utter_message(text="Enter a starting balance greater than $0.")
            return [SlotSet("starting_balance", None), SlotSet("practice_status", "awaiting_balance")]

        try:
            payload = deck_request("new/shuffle/", deck_count=DEFAULT_DECK_COUNT)
        except (requests.RequestException, ValueError, KeyError):
            dispatcher.utter_message(
                text="I couldn't set up the card shoe through the Deck of Cards API. Please try again."
            )
            return [SlotSet("practice_status", "api_error")]

        dispatcher.utter_message(
            text=f"Your starting balance is ${balance:.2f}. The {DEFAULT_DECK_COUNT}-deck shoe is ready."
        )
        return [
            SlotSet("practice_balance", balance),
            SlotSet("practice_deck_id", payload["deck_id"]),
            SlotSet("cards_remaining", payload["remaining"]),
            SlotSet("practice_bet", None),
            SlotSet("practice_player_hand", []),
            SlotSet("practice_dealer_hand", []),
            SlotSet("dealer_hole_card", None),
            SlotSet("round_result", None),
            SlotSet("continue_playing", None),
            SlotSet("practice_status", "awaiting_bet"),
        ]


class DealPracticeBlackjack(Action):
    def name(self) -> str:
        return "action_deal_practice_blackjack"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker,
            domain: dict[str, Any]) -> list[EventType]:
        balance = float(tracker.get_slot("practice_balance") or 0)
        bet = parse_money(tracker.get_slot("practice_bet"))
        deck_id = tracker.get_slot("practice_deck_id")

        if bet is None or bet <= 0 or bet > balance:
            dispatcher.utter_message(
                text=f"Choose a bet between $0.01 and your ${balance:.2f} balance."
            )
            return [SlotSet("practice_bet", None), SlotSet("practice_status", "awaiting_bet")]
        if not deck_id:
            dispatcher.utter_message(text="The card shoe has not been set up yet.")
            return [SlotSet("practice_status", "awaiting_balance")]

        try:
            remaining = int(tracker.get_slot("cards_remaining") or 0)
            if remaining < 20:
                shuffled = deck_request(f"{deck_id}/shuffle/")
                remaining = int(shuffled["remaining"])
                dispatcher.utter_message(text="The shoe was running low, so the dealer reshuffled it.")
            cards, remaining = draw_cards(str(deck_id), 4)
        except (requests.RequestException, ValueError, KeyError):
            dispatcher.utter_message(text="I couldn't draw cards from the API. Your bet was not charged.")
            return [SlotSet("practice_status", "api_error")]

        player_hand = [cards[0], cards[2]]
        dealer_hand = [cards[1], cards[3]]
        balance -= bet
        player_total, _ = api_hand_score(player_hand)
        dealer_total, _ = api_hand_score(dealer_hand)

        dispatcher.utter_message(
            text=(
                f"You bet ${bet:.2f}. Dealer shows {card_name(dealer_hand[0])}. "
                f"You have {card_name(player_hand[0])} and {card_name(player_hand[1])} "
                f"for {player_total}."
            )
        )

        events: list[EventType] = [
            SlotSet("practice_balance", balance),
            SlotSet("practice_player_hand", player_hand),
            SlotSet("practice_dealer_hand", dealer_hand),
            SlotSet("dealer_upcard", api_rank(dealer_hand[0])),
            SlotSet("dealer_hole_card", dealer_hand[1]),
            SlotSet("cards_remaining", remaining),
            SlotSet("practice_status", "player_turn"),
            SlotSet("round_result", None),
        ]

        player_blackjack = player_total == 21
        dealer_blackjack = dealer_total == 21
        if player_blackjack or dealer_blackjack:
            dispatcher.utter_message(
                text=f"Dealer reveals {card_name(dealer_hand[1])} for {dealer_total}."
            )
            if player_blackjack and dealer_blackjack:
                dispatcher.utter_message(text="Both have blackjack.")
                result = "push"
            elif player_blackjack:
                dispatcher.utter_message(text="Blackjack—you win!")
                result = "win"
            else:
                dispatcher.utter_message(text="Dealer has blackjack.")
                result = "loss"
            return events + settle_round(dispatcher, balance, bet, result)

        dispatcher.utter_message(text="Would you like to hit or stand?")
        return events


class PlayPracticeBlackjackMove(Action):
    def name(self) -> str:
        return "action_play_practice_blackjack_move"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker,
            domain: dict[str, Any]) -> list[EventType]:
        move = tracker.get_slot("player_move")
        deck_id = str(tracker.get_slot("practice_deck_id") or "")
        player_hand = list(tracker.get_slot("practice_player_hand") or [])
        dealer_hand = list(tracker.get_slot("practice_dealer_hand") or [])
        balance = float(tracker.get_slot("practice_balance") or 0)
        bet = float(tracker.get_slot("practice_bet") or 0)
        remaining = int(tracker.get_slot("cards_remaining") or 0)
        events: list[EventType] = []

        try:
            if move == "hit":
                cards, remaining = draw_cards(deck_id, 1)
                player_hand.append(cards[0])
                total, _ = api_hand_score(player_hand)
                dispatcher.utter_message(
                    text=f"You draw {card_name(cards[0])}. Your total is {total}."
                )
                events.extend([
                    SlotSet("practice_player_hand", player_hand),
                    SlotSet("cards_remaining", remaining),
                    SlotSet("player_move", None),
                ])
                if total > 21:
                    dispatcher.utter_message(text="Bust.")
                    return events + settle_round(dispatcher, balance, bet, "loss")
                if total < 21:
                    dispatcher.utter_message(text="Would you like to hit or stand?")
                    return events

            player_total, _ = api_hand_score(player_hand)
            dealer_total, _ = api_hand_score(dealer_hand)
            dispatcher.utter_message(
                text=f"Dealer reveals {card_name(dealer_hand[1])} for {dealer_total}."
            )
            while dealer_total < 17:
                cards, remaining = draw_cards(deck_id, 1)
                dealer_hand.append(cards[0])
                dealer_total, _ = api_hand_score(dealer_hand)
                dispatcher.utter_message(
                    text=f"Dealer draws {card_name(cards[0])} and now has {dealer_total}."
                )
        except (requests.RequestException, ValueError, KeyError):
            dispatcher.utter_message(text="I couldn't draw from the API. The round is still active.")
            return [SlotSet("practice_status", "api_error"), SlotSet("player_move", None)]

        events.extend([
            SlotSet("practice_dealer_hand", dealer_hand),
            SlotSet("cards_remaining", remaining),
        ])
        if dealer_total > 21 or player_total > dealer_total:
            result = "win"
        elif player_total == dealer_total:
            result = "push"
        else:
            result = "loss"
        return events + settle_round(dispatcher, balance, bet, result)


class ContinuePracticeBlackjack(Action):
    def name(self) -> str:
        return "action_continue_practice_blackjack"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker,
            domain: dict[str, Any]) -> list[EventType]:
        balance = float(tracker.get_slot("practice_balance") or 0)
        if balance <= 0:
            dispatcher.utter_message(text="Your balance is $0.00, so the practice session is over.")
            return [SlotSet("practice_status", "session_complete")]
        if not tracker.get_slot("continue_playing"):
            dispatcher.utter_message(text=f"Session ended with a ${balance:.2f} balance.")
            return [SlotSet("practice_status", "session_complete")]

        dispatcher.utter_message(text=f"Your balance is ${balance:.2f}. Place your next bet.")
        return [
            SlotSet("practice_bet", None),
            SlotSet("practice_player_hand", []),
            SlotSet("practice_dealer_hand", []),
            SlotSet("dealer_hole_card", None),
            SlotSet("round_result", None),
            SlotSet("player_move", None),
            SlotSet("continue_playing", None),
            SlotSet("practice_status", "awaiting_bet"),
        ]
