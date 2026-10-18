from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

PatientId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class MedicineInput(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    dosage: str | None = Field(default=None, max_length=200)
    frequency: str | None = Field(default=None, max_length=200)
    duration: str | None = Field(default=None, max_length=200)


class VisitCreate(BaseModel):
    patient_id: PatientId
    patient_name: str | None = Field(default=None, max_length=200)
    visit_date: date
    condition: str = Field(min_length=1, max_length=500)
    medicines: list[MedicineInput] = Field(default_factory=list, max_length=100)
    notes: str | None = Field(default=None, max_length=20_000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    patient_id: PatientId | None = None


class ChatResponse(BaseModel):
    patient_id: str
    answer: str
    source: str
