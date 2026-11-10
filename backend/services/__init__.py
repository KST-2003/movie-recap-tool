"""Business logic shared by the api/ routers: no FastAPI routing here, just functions a router calls.
(Raising fastapi.HTTPException from a service function is fine -- it's an ordinary exception class, not a framework
dependency; what this layer must NOT do is read a Request/Response or register a route.)"""
