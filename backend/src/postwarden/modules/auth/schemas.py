"""Pydantic request models for the auth module's write routes. Same
convention every prior module's `schemas.py` established: response
shapes stay plain dicts, only request bodies get a model."""
from pydantic import BaseModel


class LoginRequest(BaseModel):
    """Body of `POST /login`. `remember` replaces legacy's `remember`
    checkbox form field (present/absent -> `Form(None)`) with a real
    bool — a JSON body has no equivalent of an unchecked checkbox simply
    not appearing in the form data, so this is a plain, explicit field
    instead."""
    username: str
    password: str
    remember: bool = False


class ChangeUsernameRequest(BaseModel):
    """Body of `POST /settings/username`."""
    username: str


class ChangePasswordRequest(BaseModel):
    """Body of `POST /settings/password`."""
    current_password: str
    new_password: str
    confirm_password: str
