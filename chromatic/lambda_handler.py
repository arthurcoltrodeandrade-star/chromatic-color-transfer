"""AWS-specific adapter, kept out of local ASGI startup."""

from mangum import Mangum

from chromatic.api import app

handler = Mangum(app, lifespan="off")
