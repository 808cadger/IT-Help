import bcrypt
from dataclasses import dataclass
from .database import Database


ROLES = ["Admin", "IT_Staff", "Standard_User", "Restricted"]

ROLE_PERMISSIONS = {
    "Admin":         {"settings": True, "inventory": True, "permissions": True, "audit": True},
    "IT_Staff":      {"settings": True, "inventory": True, "permissions": False, "audit": True},
    "Standard_User": {"settings": False, "inventory": True, "permissions": False, "audit": False},
    "Restricted":    {"settings": False, "inventory": False, "permissions": False, "audit": False},
}


@dataclass
class User:
    id: int
    username: str
    email: str
    role: str

    def can(self, action: str) -> bool:
        return ROLE_PERMISSIONS.get(self.role, {}).get(action, False)


class AuthManager:
    def __init__(self, db: Database):
        self.db = db
        self._ensure_default_admin()

    def _ensure_default_admin(self):
        if not self.db.get_user("admin"):
            self.db.create_user(
                username="admin",
                email="admin@local",
                role="Admin",
                password_hash=self._hash("admin123"),
            )

    def _hash(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def login(self, username: str, password: str) -> User | None:
        row = self.db.get_user(username)
        if not row:
            return None
        if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
            return None
        return User(id=row["id"], username=row["username"],
                    email=row["email"] or "", role=row["role"])

    def create_user(self, username: str, email: str, role: str, password: str):
        self.db.create_user(username, email, role, self._hash(password))

    def change_password(self, username: str, new_password: str):
        with self.db.conn() as c:
            c.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (self._hash(new_password), username),
            )
