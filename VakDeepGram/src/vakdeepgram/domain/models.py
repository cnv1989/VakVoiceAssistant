"""Domain model placeholders for incremental migration.

Concrete models currently remain in provider/business modules.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CustomerRef:
    id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
