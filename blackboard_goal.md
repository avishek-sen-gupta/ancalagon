Three analysts share one blackboard at ./bb/blackboard.md and must reach a joint account
of how a tool call travels from the model to a result on disk.

Delegate one analyst per subsystem. Give each of them, in its goal, its own subsystem and
the blackboard's path:

1. The registry. How a tool declares its arguments, how a call's JSON becomes a typed
   object, and what a tool hands back.
2. The session. How a turn is taken, which tools are offered on which turn, and how a
   tool result becomes an outcome.
3. The workspace and the tool context. What bounds where a tool may read and write, and
   where a tool's full output lands.

The three accounts have to meet. The registry decides what a tool receives, the session
decides when it is called, and the workspace decides what it may touch — so each analyst
must read the others' entries and say where their claims join or disagree with its own.

Answer with the joint account, naming the files it rests on, and say plainly anywhere the
three of them did not agree.
