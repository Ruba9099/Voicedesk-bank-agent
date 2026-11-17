"""Fictional demo data. None of these people, CNICs or accounts are real."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models, security
from .config import Settings

DEMO_OPERATORS = [("Ayesha Khan", "busy"), ("Bilal Ahmed", "offline")]

# (name, cnic, dob, phone, address, [(acct_no, type, balance)], [(last4, type, status, acct_index)])
DEMO_CUSTOMERS = [
    ("Ahmed Raza", "3520212345671", date(1990, 3, 15), "+923001234567",
     "House 12, Street 5, Gulberg III, Lahore",
     [("0001-1001-0001", "savings", "250000.50")],
     [("4321", "debit", "active", 0), ("9876", "credit", "inactive", 0)]),
    ("Fatima Noor", "4210176543218", date(1985, 11, 2), "+923214567890",
     "Flat 4B, Clifton Block 5, Karachi",
     [("0002-2002-0002", "current", "1250000.00"), ("0002-2002-0003", "savings", "75500.75")],
     [("5544", "debit", "active", 0)]),
    ("Usman Tariq", "6110111223345", date(2000, 7, 21), "+923335550101",
     "House 8, Street 14, F-10/2, Islamabad",
     [("0003-3003-0001", "savings", "18250.00")],
     [("3002", "debit", "inactive", 0)]),
]


def seed_demo_data(db: Session, settings: Settings) -> bool:
    if db.scalar(select(func.count()).select_from(models.Customer)):
        return False
    for name, status in DEMO_OPERATORS:
        db.add(models.Operator(name=name, status=status))
    for name, cnic, dob, phone, address, accounts, cards in DEMO_CUSTOMERS:
        cust = models.Customer(
            full_name=name,
            cnic_hash=security.hash_cnic(cnic, settings.cnic_pepper),
            cnic_masked=security.mask_cnic(cnic),
            dob=dob, phone=phone, address=address,
        )
        db.add(cust)
        db.flush()
        acct_rows = []
        for number, kind, balance in accounts:
            acct = models.Account(customer_id=cust.id, account_number=number,
                                  account_type=kind, balance=Decimal(balance))
            db.add(acct)
            acct_rows.append(acct)
        db.flush()
        for last4, ctype, status, idx in cards:
            db.add(models.Card(customer_id=cust.id, account_id=acct_rows[idx].id,
                               card_last4=last4, card_type=ctype, status=status))
    db.commit()
    return True
