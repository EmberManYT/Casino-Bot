"""Run against the trained Rasa model and real in-process custom actions.

From the project directory: .venv/bin/python tests/test_conversations.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rasa.core.agent import Agent
from rasa.core.config.configuration import Configuration
from rasa.utils.endpoints import EndpointConfig

CASES = [
    [
        ('hi', 'first two cards'),
        ('10 and 4', 'dealer showing'),
        ('10', 'hard 14', 'HIT'),
        ('hit', 'did you draw'),
        ('6', 'hard 20', 'STAND'),
        ('stand', 'You stand on 20', 'Round complete'),
        ('new hand', 'first two cards'),
        ('ace and 7', 'dealer showing'),
        ('9', 'soft 18', 'HIT'),
        ('hit', 'did you draw'),
        ('ace', 'soft 19', 'STAND'),
        ('hit', 'did you draw'),
        ('5', 'hard 14', 'HIT'),
        ('hit', 'did you draw'),
        ('king', 'Bust', 'Round complete'),
    ],
    [('help me with blackjack', 'first two cards'),
     ('ace and king', 'dealer showing'), ('6', 'Blackjack', 'Round complete')],
    [('hi', 'first two cards'), ('banana', 'exactly two'),
     ('10 and 8', 'dealer showing'), ('banana', 'exactly one'),
     ('6', 'hard 18', 'STAND'), ('hit', 'did you draw'),
     ('banana', 'one card rank'), ('2', 'hard 20', 'STAND')],
]

async def main():
    Configuration.initialise_endpoints(ROOT / 'endpoints.yml')
    agent = Agent.load(str(ROOT / 'models/blackjack-happy-path.tar.gz'),
                       action_endpoint=EndpointConfig(actions_module='actions.actions'))
    turns = 0
    for index, case in enumerate(CASES):
        for message, *expected in case:
            responses = await agent.handle_text(message, sender_id=f'regression-{index}')
            text = '\n'.join(response.get('text', '') for response in responses)
            assert all(fragment in text for fragment in expected), (message, expected, text)
            print(f'PASS {message!r} -> {text}', flush=True)
            turns += 1
    print(f'PASS: {len(CASES)} conversations, {turns} turns')

if __name__ == '__main__':
    asyncio.run(main())
