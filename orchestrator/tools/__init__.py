"""
orchestrator/tools
=====================
LangChain tool definitions -- the things the agent (`app/agent.py`) can
actually call. See `orchestrator/DESIGN.md` §4 for the "ready vs. stub"
policy this package enforces: `registry.py` is the only place that decides
which tools are ever bound to the LLM.
"""
