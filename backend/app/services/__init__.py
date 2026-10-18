"""Glue between the HTTP routes and the domain modules: tenant bootstrap from seed data, loading one business's
engine inputs, and the process-wide runtime (simulated clock, audit log, one gateway per business).

Routes in api/ stay thin and call only into here or into domain modules. Nothing here imports app.executor: actions
reach executors only through a Gateway (invariant 1).
"""
