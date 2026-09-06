"""
orchestrator/app/api
=======================
One file per endpoint group from `ui/DESIGN.md` §6/§8, each a thin FastAPI
`APIRouter`. These files intentionally do NOT define strict Pydantic
models for the request/response bodies (`ui/api/types.ts`'s `ContextItem`
union in particular would need a fair bit of discriminated-union
boilerplate to mirror exactly) -- request bodies are accepted as plain
JSON dicts and read defensively, and response bodies are plain dicts built
to match `ui/DESIGN.md` §6's shapes field-for-field. This keeps the route
code short and easy to read; `ui/src/api/types.ts` remains the single
source of truth for the shapes themselves.
"""
