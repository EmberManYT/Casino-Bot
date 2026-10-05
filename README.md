# Blackjack advice bot

A Rasa assistant for **hit-or-stand advice**. Enter your first two cards together,
then the dealer's visible card. After a hit, enter the card you actually drew.
It does not deal cards or recommend splits, doubles, insurance, or surrender.

## Run

From this directory, with your existing `RASA_LICENSE` environment variable set:

```sh
uv run blackjack-bot
```

This trains the current configuration and opens the Rasa chat using that exact
model. Training can take a minute; unchanged training components are cached.
Custom actions run inside Rasa, so no second terminal or action server is needed.

## Verified demo

```text
You: hi
Bot: What are your first two cards? For example: ace and 7.
You: 10 and 4
Bot: What card is the dealer showing?
You: 10
Bot: You have a hard 14 against the dealer's 10. Basic strategy says: HIT.
You: hit
Bot: What card did you draw?
You: 6
Bot: You have a hard 20 against the dealer's 10. Basic strategy says: STAND.
You: stand
Bot: You stand on 20.
You: new hand
```

Use ranks such as `ace`, `king`, `queen`, `jack`, or `2` through `10`.
Number words such as `seven` work too. Use `ace and 7`, not a hand total like `18`.

## Regression check

```sh
.venv/bin/rasa train --fixed-model-name blackjack-happy-path
.venv/bin/python tests/test_conversations.py
```

Tests use the trained Rasa model and actual custom actions, including hitting,
standing, a fresh hand, soft aces, blackjack, bust, and invalid card inputs.

Older model archives were trained with a different card-collection flow and
must not be used with the current actions. The launcher selects the rebuilt
`blackjack-happy-path.tar.gz` explicitly.
