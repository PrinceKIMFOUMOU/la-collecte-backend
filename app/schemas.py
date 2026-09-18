from pydantic import BaseModel, EmailStr # type: ignore


class UserCreate(BaseModel):
    nom: str
    prenom: str
    email: EmailStr
    password: str
    filiere_id: int
    niveau_id: int

class UserLogin(BaseModel):
    email : EmailStr
    password: str

class MatiereCreate(BaseModel):
    nom: str
    niveau_id: int
    semestre_id: int