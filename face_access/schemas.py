from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BootstrapRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=128)
    person_id: str | None = Field(default=None, max_length=64)


class LoginRequest(BaseModel):
    username: str
    password: str


class AdminResponse(BaseModel):
    username: str
    person_id: str | None
    role: str
    operation_level: str


OperationLevel = Literal["A", "B", "C", "D"]
PersonStatus = Literal["active", "inactive"]


class PersonCreate(BaseModel):
    person_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=128)
    department: str = Field(default="", max_length=128)
    position: str = Field(default="", max_length=128)
    operation_level: OperationLevel
    notes: str = Field(default="", max_length=1000)


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    department: str | None = Field(default=None, max_length=128)
    position: str | None = Field(default=None, max_length=128)
    operation_level: OperationLevel | None = None
    status: PersonStatus | None = None
    notes: str | None = Field(default=None, max_length=1000)


class PersonResponse(BaseModel):
    person_id: str
    name: str
    department: str
    position: str
    operation_level: OperationLevel
    status: PersonStatus
    notes: str
    registered_at: datetime
    deleted_at: datetime | None
