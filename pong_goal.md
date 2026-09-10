Build a playable paddle game in the terminal: one ball, one paddle, and walls.

The ball moves on its own and bounces off the left, right and top walls. The paddle sits
along the bottom and is moved left and right with the arrow keys. If the ball gets past
the paddle it is a miss. Quit with q.

It must end up as three files in the working directory:

- engine.py       the rules, as pure Python, with no terminal code
- test_engine.py  plain asserts, run with `python3 test_engine.py`, exiting 0 when they pass
- game.py         curses drawing, keyboard input, and the main loop

Delegate the engine first and collect it. Then read the engine yourself and delegate the
terminal game, telling that agent the engine's real class and method names — it cannot see
anything you were not explicit about in its goal.

Answer with the command to run the game, the controls, and one line on what each file does.
