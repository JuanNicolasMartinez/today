"""Generador de datos ficticios para la demo, las pruebas y las capturas."""

from __future__ import annotations

import datetime as dt
import random
import secrets
from decimal import Decimal

from web_app.services import accounts

_FIRST = ["Ana", "Luis", "Camila", "Andrés", "Valentina", "Mateo", "Sofía", "Julián",
          "Daniela", "Santiago", "Isabela", "Tomás", "Mariana", "Felipe", "Laura", "Simón"]
_LAST = ["Rojas", "Pardo", "Quintero", "Salazar", "Ospina", "Cárdenas", "Mejía", "Duarte",
         "Arango", "Velasco", "Restrepo", "Gaitán", "Montoya", "Herrera", "Zuluaga", "Lozano"]
_CITIES = ["Bogotá", "Medellín", "Cali", "Barranquilla", "Bucaramanga", "Manizales",
           "Pereira", "Cartagena", "Tunja", "Pasto"]
_ALLERGIES = ["", "", "Penicilina", "Polen", "Maní", "Mariscos", "Lactosa"]
_CONDITIONS = ["", "", "", "Asma leve", "Hipertensión controlada", "Migraña"]


def fake_registration(rng: random.Random, index: int) -> accounts.RegistrationData:
    first, last = rng.choice(_FIRST), rng.choice(_LAST)
    handle = f"demo.{first.lower()}{index:02d}".translate(str.maketrans("áéíóúñ", "aeioun"))
    password = "Demo-" + secrets.token_urlsafe(18)
    return accounts.RegistrationData(
        username=handle,
        email=f"{handle}@example.test",
        password=password,
        password_confirm=password,
        full_name=f"{first} {last} {rng.choice(_LAST)}",
        document_id=str(rng.randint(10_000_000, 1_199_999_999)),
        birth_date=dt.date(rng.randint(1958, 2004), rng.randint(1, 12), rng.randint(1, 28)),
        phone=f"+57 3{rng.randint(0, 2)}{rng.randint(0, 9)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}",
        city=rng.choice(_CITIES),
        blood_type=rng.choice(accounts.BLOOD_TYPES),
        allergies=rng.choice(_ALLERGIES),
        chronic_condition=rng.choice(_CONDITIONS),
        credit_score=rng.randint(380, 920),
        monthly_income=Decimal(rng.randrange(1_400_000, 18_000_000, 50_000)),
        outstanding_debt=Decimal(rng.randrange(0, 60_000_000, 100_000)),
    )
