from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form # pyright: ignore[reportMissingImports]
from fastapi.middleware.cors import CORSMiddleware # pyright: ignore[reportMissingImports]
from fastapi.security import OAuth2PasswordRequestForm # pyright: ignore[reportMissingImports]
from fastapi.responses import FileResponse, RedirectResponse # pyright: ignore[reportMissingImports]
from app.supabase_client import supabase
from fastapi.responses import Response # type: ignore
from app.database import get_connection
from app.schemas import UserCreate, UserLogin, MatiereCreate
from app.security import create_access_token, verify_token, verify_admin
from pypdf import PdfReader # pyright: ignore[reportMissingImports]
from psycopg2 import Error # pyright: ignore[reportMissingModuleSource]

import bcrypt # type: ignore
import os
import shutil
import uuid
import httpx # type: ignore


# ==========================================================
# APPLICATION
# ==========================================================

app = FastAPI(
    title="La Collecte API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://la-collecte-frontend.onrender.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def valider_pdf(fichier_path):
    try:
        reader = PdfReader(fichier_path)

        if len(reader.pages) == 0:
            return False

        return True

    except Exception:
        return False

MAX_PDF_SIZE = 500 * 1024 * 1024 


def verifier_taille_pdf(fichier_path):
    taille = os.path.getsize(fichier_path)

    if taille > MAX_PDF_SIZE:
        if os.path.exists(fichier_path):
            os.remove(fichier_path)

        raise HTTPException(
            status_code=413,
            detail="Le fichier PDF dépasse la taille maximale autorisée de 500 Mo"
        )

def fermer_connexion(cursor, connection):
    if cursor:
        cursor.close()

    if connection:
        connection.close()
    
# ==========================================================
# ROUTE PRINCIPALE
# ==========================================================

@app.get("/")
def root():
    return {
        "message": "Bienvenue sur l'API La Collecte"
    }


# ==========================================================
# TEST DATABASE
# ==========================================================

@app.get("/test-db")
def test_db():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("SELECT 1;")
    result = cursor.fetchone()

    cursor.close()
    connection.close()

    return {
        "database": "connectée",
        "resultat": result[0]
    }


# ==========================================================
# NIVEAUX
# ==========================================================

@app.get("/niveaux")
def get_niveaux():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, nom
        FROM niveaux
        ORDER BY id;
    """)

    niveaux = cursor.fetchall()

    cursor.close()
    connection.close()

    return [
        {
            "id": niveau[0],
            "nom": niveau[1]
        }
        for niveau in niveaux
    ]


# ==========================================================
# SEMESTRES
# ==========================================================

@app.get("/semestres")
def get_semestres():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, nom
        FROM semestres
        ORDER BY id;
    """)

    semestres = cursor.fetchall()

    cursor.close()
    connection.close()

    return [
        {
            "id": semestre[0],
            "nom": semestre[1]
        }
        for semestre in semestres
    ]


# ==========================================================
# TYPES DE RESSOURCES
# ==========================================================

@app.get("/types-ressources")
def get_types_ressources():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, nom
        FROM types_ressources
        ORDER BY id;
    """)

    types = cursor.fetchall()

    cursor.close()
    connection.close()

    return [
        {
            "id": type_ressource[0],
            "nom": type_ressource[1]
        }
        for type_ressource in types
    ]


# ==========================================================
# MATIERES
# ==========================================================

@app.get("/matieres")
def get_matieres(
    niveau_id: int | None = None,
    semestre_id: int | None = None,
    token_data: dict = Depends(verify_token)
):
    connection = get_connection()
    cursor = connection.cursor()

    query = """
        SELECT id, nom, niveau_id, semestre_id
        FROM matieres
        WHERE 1 = 1
    """

    params = []

    if niveau_id is not None:
        query += " AND niveau_id = %s"
        params.append(niveau_id)

    if semestre_id is not None:
        query += " AND semestre_id = %s"
        params.append(semestre_id)

    query += " ORDER BY nom"

    try:
        cursor.execute(query, params)
        matieres = cursor.fetchall()

        return [
            {
                "id": matiere[0],
                "nom": matiere[1],
                "niveau_id": matiere[2],
                "semestre_id": matiere[3]
            }
            for matiere in matieres
        ]

    finally:
        cursor.close()
        connection.close()

# ==========================================================
# FILIERES
# ==========================================================

@app.get("/filieres")
def get_filieres():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, nom
        FROM filieres
        ORDER BY id;
    """)

    filieres = cursor.fetchall()

    cursor.close()
    connection.close()

    return [
        {
            "id": filiere[0],
            "nom": filiere[1]
        }
        for filiere in filieres
    ]


# ==========================================================
# CREER UN UTILISATEUR
# ==========================================================

@app.post("/users")
def create_user(user: UserCreate):

    connection = get_connection()
    cursor = connection.cursor()

    # Vérifier si l'email existe déjà
    cursor.execute("""
        SELECT id
        FROM users
        WHERE email = %s;
    """, (user.email,))

    existing_user = cursor.fetchone()

    if existing_user is not None:
        cursor.close()
        connection.close()

        raise HTTPException(
            status_code=400,
            detail="Cette adresse e-mail est déjà utilisée"
        )

    # Vérifier la filière
    cursor.execute("""
        SELECT id
        FROM filieres
        WHERE id = %s;
    """, (user.filiere_id,))

    filiere = cursor.fetchone()

    if filiere is None:
        cursor.close()
        connection.close()

        raise HTTPException(
            status_code=400,
            detail="Filière invalide"
        )

    # Vérifier le niveau
    cursor.execute("""
        SELECT id
        FROM niveaux
        WHERE id = %s;
    """, (user.niveau_id,))

    niveau = cursor.fetchone()

    if niveau is None:
        cursor.close()
        connection.close()

        raise HTTPException(
            status_code=400,
            detail="Niveau invalide"
        )

    # Rôle étudiant = 1
    role_id = 1

    # Hash du mot de passe
    password_hash = bcrypt.hashpw(
        user.password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    # Création utilisateur
    cursor.execute("""
        INSERT INTO users (
            nom,
            prenom,
            email,
            password_hash,
            role_id,
            filiere_id,
            niveau_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
    """, (
        user.nom,
        user.prenom,
        user.email,
        password_hash,
        role_id,
        user.filiere_id,
        user.niveau_id
    ))

    user_id = cursor.fetchone()[0]

    connection.commit()

    cursor.close()
    connection.close()

    # ==========================================
    # CONNEXION AUTOMATIQUE APRÈS INSCRIPTION
    # ==========================================

    access_token = create_access_token({
        "sub": str(user_id),
        "email": user.email,
        "role_id": role_id
    })

    return {
        "message": "Inscription réussie",
        "user_id": user_id,
        "access_token": access_token,
        "token_type": "bearer",
        "role_id": role_id
    }

# ==========================================================
# LOGIN
# ==========================================================

@app.post("/login")
def login(user: UserLogin):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            nom,
            prenom,
            email,
            password_hash,
            role_id
        FROM users
        WHERE email = %s;
    """, (user.email,))

    existing_user = cursor.fetchone()

    cursor.close()
    connection.close()

    if existing_user is None:
        raise HTTPException(
            status_code=401,
            detail="E-mail ou mot de passe incorrect"
        )

    password_correct = bcrypt.checkpw(
        user.password.encode("utf-8"),
        existing_user[4].encode("utf-8")
    )

    if not password_correct:
        raise HTTPException(
            status_code=401,
            detail="E-mail ou mot de passe incorrect"
        )

    access_token = create_access_token({
        "sub": str(existing_user[0]),
        "email": existing_user[3],
        "role_id": existing_user[5]
    })

    return {
        "message": "Connexion réussie",
        "access_token": access_token,
        "token_type": "bearer",
        "role_id": existing_user[5]
    }


# ==========================================================
# PROFIL
# ==========================================================

@app.get("/profil")
def profil(token_data: dict = Depends(verify_token)):
    return {
        "message": "Token valide",
        "user_id": token_data.get("sub"),
        "email": token_data.get("email"),
        "role_id": token_data.get("role_id")
    }


# ==========================================================
# ME
# ==========================================================

@app.get("/me")
def me(token_data: dict = Depends(verify_token)):

    connection = get_connection()
    cursor = connection.cursor()

    user_id = int(token_data["sub"])

    cursor.execute("""
        SELECT
            u.id,
            u.nom,
            u.prenom,
            u.email,
            r.nom AS role,
            f.nom AS filiere,
            n.nom AS niveau
        FROM users u
        JOIN roles r
            ON u.role_id = r.id
        JOIN filieres f
            ON u.filiere_id = f.id
        JOIN niveaux n
            ON u.niveau_id = n.id
        WHERE u.id = %s;
    """, (user_id,))

    user = cursor.fetchone()

    cursor.close()
    connection.close()

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Utilisateur introuvable"
        )

    return {
        "id": user[0],
        "nom": user[1],
        "prenom": user[2],
        "email": user[3],
        "role": user[4],
        "filiere": user[5],
        "niveau": user[6]
    }


# ==========================================================
# TOKEN - SWAGGER / OAUTH2
# ==========================================================

@app.post("/token")
def token(form_data: OAuth2PasswordRequestForm = Depends()):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            id,
            nom,
            prenom,
            email,
            password_hash,
            role_id
        FROM users
        WHERE email = %s;
    """, (form_data.username,))

    existing_user = cursor.fetchone()

    cursor.close()
    connection.close()

    if existing_user is None:
        raise HTTPException(
            status_code=401,
            detail="E-mail ou mot de passe incorrect"
        )

    password_correct = bcrypt.checkpw(
        form_data.password.encode("utf-8"),
        existing_user[4].encode("utf-8")
    )

    if not password_correct:
        raise HTTPException(
            status_code=401,
            detail="E-mail ou mot de passe incorrect"
        )

    access_token = create_access_token({
        "sub": str(existing_user[0]),
        "email": existing_user[3],
        "role_id": existing_user[5]
    })

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


# ==========================================================
# AJOUTER UNE RESSOURCE
# ADMIN UNIQUEMENT
# ==========================================================

@app.post("/ressources")
async def create_ressource(
    titre: str = Form(...),
    description: str = Form(""),
    type_ressource_id: int = Form(...),
    annee_academique_id: int = Form(...),
    niveau_id: int = Form(...),
    semestre_id: int = Form(...),
    matiere_id: int = Form(...),
    fichier: UploadFile = File(...),
    token_data: dict = Depends(verify_admin)
):

    # ==========================================
    # 1. VÉRIFIER LE TYPE DE FICHIER
    # ==========================================

    if fichier.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Seuls les fichiers PDF sont autorisés"
        )

    # Nom original
    fichier_nom = fichier.filename

    # Extension
    extension = os.path.splitext(fichier_nom)[1].lower()

    # Vérification supplémentaire de l'extension
    if extension != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Le fichier doit avoir l'extension .pdf"
        )

    # ==========================================
    # 2. GÉNÉRER UN NOM UNIQUE
    # ==========================================

    nom_unique = f"{uuid.uuid4()}.pdf"

    # ==========================================
    # 3. CHEMIN TEMPORAIRE LOCAL
    # ==========================================

    os.makedirs("uploads", exist_ok=True)

    fichier_path = os.path.join(
        "uploads",
        nom_unique
    )

    try:

        # ==========================================
        # 4. LIRE LE FICHIER
        # ==========================================

        contenu = await fichier.read()

        if not contenu:
            raise HTTPException(
                status_code=400,
                detail="Le fichier est vide"
            )

        # ==========================================
        # 5. SAUVEGARDE TEMPORAIRE
        # ==========================================

        with open(fichier_path, "wb") as buffer:
            buffer.write(contenu)

        # ==========================================
        # 6. VÉRIFIER LA TAILLE
        # ==========================================

        verifier_taille_pdf(fichier_path)

        # ==========================================
        # 7. VÉRIFIER QUE C'EST UN VRAI PDF
        # ==========================================

        if not valider_pdf(fichier_path):
            raise HTTPException(
                status_code=400,
                detail="Le fichier fourni n'est pas un PDF valide"
            )

        # ==========================================
        # 8. CONFIGURATION SUPABASE
        # ==========================================

        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

        if not SUPABASE_URL:
            raise HTTPException(
                status_code=500,
                detail="SUPABASE_URL est absente du fichier .env"
            )

        if not SUPABASE_SECRET_KEY:
            raise HTTPException(
                status_code=500,
                detail="SUPABASE_SECRET_KEY est absente du fichier .env"
            )

        # ==========================================
        # 9. URL SUPABASE STORAGE
        # ==========================================

        storage_url = (
            f"{SUPABASE_URL.rstrip('/')}"
            f"/storage/v1/object/ressources/{nom_unique}"
        )

        headers = {
            "apikey": SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            "Content-Type": "application/pdf"
        }

        # ==========================================
        # 10. ENVOYER LE PDF À SUPABASE
        # ==========================================

        response = httpx.post(
            storage_url,
            headers=headers,
            content=contenu,
            timeout=120
        )

        print("SUPABASE STATUS :", response.status_code)
        print("SUPABASE REPONSE :", response.text)

        # Vérifier la réponse
        if response.status_code >= 400:

            raise HTTPException(
                status_code=500,
                detail=(
                    f"Erreur Supabase Storage "
                    f"{response.status_code} : "
                    f"{response.text}"
                )
            )

        # ==========================================
        # 11. CHEMIN SUPABASE
        # ==========================================

        supabase_path = nom_unique

        # ==========================================
        # 12. ENREGISTRER DANS POSTGRESQL
        # ==========================================

        connection = get_connection()
        cursor = connection.cursor()

        try:

            created_by = int(token_data["sub"])

            cursor.execute("""
                INSERT INTO ressources (
                    titre,
                    description,
                    fichier_nom,
                    fichier_path,
                    type_ressource_id,
                    annee_academique_id,
                    niveau_id,
                    semestre_id,
                    matiere_id,
                    created_by
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                RETURNING id;
            """, (
                titre,
                description,
                fichier_nom,
                supabase_path,
                type_ressource_id,
                annee_academique_id,
                niveau_id,
                semestre_id,
                matiere_id,
                created_by
            ))

            ressource_id = cursor.fetchone()[0]

            connection.commit()

        except Exception:
            connection.rollback()
            raise

        finally:
            cursor.close()
            connection.close()

        # ==========================================
        # 13. RÉPONSE
        # ==========================================

        return {
            "message": "Ressource ajoutée avec succès",
            "ressource_id": ressource_id,
            "fichier": fichier_nom
        }

    except HTTPException:
        raise

    except Exception as e:

        print("ERREUR AJOUT RESSOURCE :", repr(e))

        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'ajout de la ressource : {str(e)}"
        )

    finally:

        # ==========================================
        # 14. SUPPRIMER LE FICHIER TEMPORAIRE
        # ==========================================

        if os.path.exists(fichier_path):
            os.remove(fichier_path)
    

@app.put("/admin/ressources/{ressource_id}")
def update_ressource(
    ressource_id: int,
    titre: str = Form(...),
    description: str = Form(""),
    type_ressource_id: int = Form(...),
    annee_academique_id: int = Form(...),
    niveau_id: int = Form(...),
    semestre_id: int = Form(...),
    matiere_id: int = Form(...),
    token_data: dict = Depends(verify_admin)
):
    connection = get_connection()
    cursor = connection.cursor()

    # Vérifier que la ressource existe
    cursor.execute(
        "SELECT id FROM ressources WHERE id = %s;",
        (ressource_id,)
    )

    if cursor.fetchone() is None:
        cursor.close()
        connection.close()
        raise HTTPException(
            status_code=404,
            detail="Ressource introuvable"
        )

    # Vérifier les références
    cursor.execute(
        "SELECT id FROM types_ressources WHERE id = %s;",
        (type_ressource_id,)
    )
    if cursor.fetchone() is None:
        cursor.close()
        connection.close()
        raise HTTPException(
            status_code=400,
            detail="Type de ressource invalide"
        )

    cursor.execute(
        "SELECT id FROM annees_academiques WHERE id = %s;",
        (annee_academique_id,)
    )
    if cursor.fetchone() is None:
        cursor.close()
        connection.close()
        raise HTTPException(
            status_code=400,
            detail="Année académique invalide"
        )

    cursor.execute(
        "SELECT id FROM niveaux WHERE id = %s;",
        (niveau_id,)
    )
    if cursor.fetchone() is None:
        cursor.close()
        connection.close()
        raise HTTPException(
            status_code=400,
            detail="Niveau invalide"
        )

    cursor.execute(
        "SELECT id FROM semestres WHERE id = %s;",
        (semestre_id,)
    )
    if cursor.fetchone() is None:
        cursor.close()
        connection.close()
        raise HTTPException(
            status_code=400,
            detail="Semestre invalide"
        )

    cursor.execute(
        "SELECT id FROM matieres WHERE id = %s;",
        (matiere_id,)
    )
    if cursor.fetchone() is None:
        cursor.close()
        connection.close()
        raise HTTPException(
            status_code=400,
            detail="Matière invalide"
        )

    # Mise à jour
    cursor.execute(
        """
        UPDATE ressources
        SET
            titre = %s,
            description = %s,
            type_ressource_id = %s,
            annee_academique_id = %s,
            niveau_id = %s,
            semestre_id = %s,
            matiere_id = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
        """,
        (
            titre,
            description,
            type_ressource_id,
            annee_academique_id,
            niveau_id,
            semestre_id,
            matiere_id,
            ressource_id
        )
    )

    connection.commit()

    cursor.close()
    connection.close()

    return {
        "message": "Ressource modifiée avec succès",
        "ressource_id": ressource_id
    }


@app.put("/admin/ressources/{ressource_id}/fichier")
async def remplacer_fichier_ressource(
    ressource_id: int,
    fichier: UploadFile = File(...),
    token_data: dict = Depends(verify_admin)
):

    # ==========================================
    # 1. VÉRIFIER LE TYPE DE FICHIER
    # ==========================================

    if fichier.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Seuls les fichiers PDF sont autorisés"
        )

    fichier_nom = fichier.filename

    extension = os.path.splitext(fichier_nom)[1].lower()

    if extension != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="Le fichier doit avoir l'extension .pdf"
        )

    # ==========================================
    # 2. LIRE LE NOUVEAU FICHIER
    # ==========================================

    contenu = await fichier.read()

    if not contenu:
        raise HTTPException(
            status_code=400,
            detail="Le fichier est vide"
        )

    # ==========================================
    # 3. NOM UNIQUE DU NOUVEAU PDF
    # ==========================================

    nom_unique = f"{uuid.uuid4()}.pdf"

    os.makedirs("uploads", exist_ok=True)

    fichier_temp = os.path.join(
        "uploads",
        nom_unique
    )

    try:

        # ==========================================
        # 4. SAUVEGARDE TEMPORAIRE
        # ==========================================

        with open(fichier_temp, "wb") as buffer:
            buffer.write(contenu)

        # ==========================================
        # 5. VÉRIFIER LA TAILLE
        # ==========================================

        verifier_taille_pdf(fichier_temp)

        # ==========================================
        # 6. VÉRIFIER QUE C'EST UN VRAI PDF
        # ==========================================

        if not valider_pdf(fichier_temp):
            raise HTTPException(
                status_code=400,
                detail="Le fichier fourni n'est pas un PDF valide"
            )

        # ==========================================
        # 7. CONFIGURATION SUPABASE
        # ==========================================

        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

        if not SUPABASE_URL:
            raise HTTPException(
                status_code=500,
                detail="SUPABASE_URL est absente du fichier .env"
            )

        if not SUPABASE_SECRET_KEY:
            raise HTTPException(
                status_code=500,
                detail="SUPABASE_SECRET_KEY est absente du fichier .env"
            )

        SUPABASE_URL = SUPABASE_URL.rstrip("/")

        # ==========================================
        # 8. RÉCUPÉRER L'ANCIEN PDF
        # ==========================================

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT fichier_path
            FROM ressources
            WHERE id = %s
        """, (ressource_id,))

        ressource = cursor.fetchone()

        cursor.close()
        connection.close()

        if not ressource:
            raise HTTPException(
                status_code=404,
                detail="Ressource introuvable"
            )

        ancien_fichier_path = ressource[0]

        # ==========================================
        # 9. UPLOADER LE NOUVEAU PDF
        # ==========================================

        upload_url = (
            f"{SUPABASE_URL}"
            f"/storage/v1/object/ressources/{nom_unique}"
        )

        headers = {
            "apikey": SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
            "Content-Type": "application/pdf"
        }

        response_upload = httpx.post(
            upload_url,
            headers=headers,
            content=contenu,
            timeout=120
        )

        print(
            "SUPABASE REMPLACEMENT STATUS :",
            response_upload.status_code
        )

        print(
            "SUPABASE REMPLACEMENT REPONSE :",
            response_upload.text
        )

        if response_upload.status_code >= 400:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Erreur Supabase Storage "
                    f"{response_upload.status_code} : "
                    f"{response_upload.text}"
                )
            )

        # ==========================================
        # 10. METTRE À JOUR POSTGRESQL
        # ==========================================

        connection = get_connection()
        cursor = connection.cursor()

        try:

            cursor.execute("""
                UPDATE ressources
                SET
                    fichier_nom = %s,
                    fichier_path = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (
                fichier_nom,
                nom_unique,
                ressource_id
            ))

            if cursor.rowcount == 0:
                connection.rollback()

                delete_new_url = (
                    f"{SUPABASE_URL}"
                    f"/storage/v1/object/ressources/{nom_unique}"
                )

                httpx.delete(
                    delete_new_url,
                    headers={
                        "apikey": SUPABASE_SECRET_KEY,
                        "Authorization":
                            f"Bearer {SUPABASE_SECRET_KEY}"
                    },
                    timeout=60
                )

                raise HTTPException(
                    status_code=404,
                    detail="Ressource introuvable"
                )

            connection.commit()

        except HTTPException:
            raise

        except Exception:
            connection.rollback()
            raise

        finally:
            cursor.close()
            connection.close()

        # ==========================================
        # 11. SUPPRIMER L'ANCIEN PDF DE SUPABASE
        # ==========================================

        if ancien_fichier_path:

            ancien_fichier_url = (
                f"{SUPABASE_URL}"
                f"/storage/v1/object/ressources/"
                f"{ancien_fichier_path}"
            )

            response_delete = httpx.delete(
                ancien_fichier_url,
                headers={
                    "apikey": SUPABASE_SECRET_KEY,
                    "Authorization":
                        f"Bearer {SUPABASE_SECRET_KEY}"
                },
                timeout=60
            )

            print(
                "SUPPRESSION ANCIEN PDF :",
                response_delete.status_code
            )

            if response_delete.status_code >= 400:
                print(
                    "ATTENTION : ancien PDF non supprimé :",
                    response_delete.text
                )

        # ==========================================
        # 12. RÉPONSE
        # ==========================================

        return {
            "message": "PDF remplacé avec succès",
            "ressource_id": ressource_id,
            "ancien_fichier": ancien_fichier_path,
            "nouveau_fichier": fichier_nom
        }

    except HTTPException:
        raise

    except Exception as e:

        print(
            "ERREUR REMPLACEMENT PDF :",
            repr(e)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Erreur lors du remplacement du PDF : "
                f"{str(e)}"
            )
        )

    finally:

        # ==========================================
        # 13. SUPPRIMER LE FICHIER TEMPORAIRE LOCAL
        # ==========================================

        if os.path.exists(fichier_temp):
            os.remove(fichier_temp)
    
# ==========================================================
# LISTE ET FILTRAGE DES RESSOURCES
# UTILISATEUR CONNECTÉ
# ==========================================================

@app.get("/ressources")
def get_ressources(
    search: str | None = None,
    type_ressource_id: int | None = None,
    annee_academique_id: int | None = None,
    niveau_id: int | None = None,
    semestre_id: int | None = None,
    matiere_id: int | None = None,
    token_data: dict = Depends(verify_token)
):

    connection = get_connection()
    cursor = connection.cursor()

    query = """
        SELECT
            r.id,
            r.titre,
            r.description,
            r.fichier_nom,
            r.fichier_path,
            tr.id AS type_ressource_id,
            tr.nom AS type_ressource,
            aa.id AS annee_academique_id,
            aa.libelle AS annee_academique,
            n.id AS niveau_id,
            n.nom AS niveau,
            s.id AS semestre_id,
            s.nom AS semestre,
            m.id AS matiere_id,
            m.nom AS matiere
        FROM ressources r
        JOIN types_ressources tr
            ON r.type_ressource_id = tr.id
        JOIN annees_academiques aa
            ON r.annee_academique_id = aa.id
        JOIN niveaux n
            ON r.niveau_id = n.id
        JOIN semestres s
            ON r.semestre_id = s.id
        JOIN matieres m
            ON r.matiere_id = m.id
        WHERE 1 = 1
    """

    params = []

    # Recherche par titre, description ou matière
    if search is not None and search.strip() != "":
        query += """
            AND (
                r.titre ILIKE %s
                OR r.description ILIKE %s
                OR m.nom ILIKE %s
            )
        """

        recherche = f"%{search.strip()}%"

        params.extend([
            recherche,
            recherche,
            recherche
        ])

    if type_ressource_id is not None:
        query += " AND r.type_ressource_id = %s"
        params.append(type_ressource_id)

    if annee_academique_id is not None:
        query += " AND r.annee_academique_id = %s"
        params.append(annee_academique_id)

    if niveau_id is not None:
        query += " AND r.niveau_id = %s"
        params.append(niveau_id)

    if semestre_id is not None:
        query += " AND r.semestre_id = %s"
        params.append(semestre_id)

    if matiere_id is not None:
        query += " AND r.matiere_id = %s"
        params.append(matiere_id)

    query += " ORDER BY r.created_at DESC;"

    cursor.execute(query, params)
    ressources = cursor.fetchall()

    cursor.close()
    connection.close()

    return [
        {
            "id": r[0],
            "titre": r[1],
            "description": r[2],
            "fichier_nom": r[3],
            "fichier_path": r[4],
            "type_ressource_id": r[5],
            "type_ressource": r[6],
            "annee_academique_id": r[7],
            "annee_academique": r[8],
            "niveau_id": r[9],
            "niveau": r[10],
            "semestre_id": r[11],
            "semestre": r[12],
            "matiere_id": r[13],
            "matiere": r[14]
        }
        for r in ressources
    ]


# ==========================================================
# OUVERTURE / TELECHARGEMENT INSTANTANÉ DU PDF
# ==========================================================

# ==========================================================
# TELECHARGER / OUVRIR LE PDF INSTANTANÉMENT
# ==========================================================

# ==========================================================
# OUVRIR LE PDF DANS LE LECTEUR DU NAVIGATEUR (SANS FORCER LE TÉLÉCHARGEMENT)
# ==========================================================

@app.get("/ressources/{ressource_id}/fichier")
def get_ressource_fichier(
    ressource_id: int
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT fichier_path
        FROM ressources
        WHERE id = %s
    """, (ressource_id,))

    ressource = cursor.fetchone()

    cursor.close()
    connection.close()

    if not ressource:
        raise HTTPException(
            status_code=404,
            detail="Ressource introuvable"
        )

    fichier_path = ressource[0]

    try:
        contenu = supabase.storage.from_("ressources").download(
            fichier_path
        )

        return Response(
            content=contenu,
            media_type="application/pdf",
            headers={
                "Content-Disposition": "inline",
                "Content-Type": "application/pdf",
                "Cache-Control": "public, max-age=86400"
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=404,
            detail=f"Fichier PDF introuvable : {str(e)}"
        )
    
# ==========================================================
# SUPPRIMER UNE RESSOURCE
# ADMIN UNIQUEMENT
# ==========================================================

@app.delete("/ressources/{ressource_id}")
def supprimer_ressource(
    ressource_id: int,
    token_data: dict = Depends(verify_admin)
):

    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

    if not SUPABASE_URL:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_URL est absente du fichier .env"
        )

    if not SUPABASE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_SECRET_KEY est absente du fichier .env"
        )

    SUPABASE_URL = SUPABASE_URL.rstrip("/")

    # ==========================================
    # 1. RÉCUPÉRER LA RESSOURCE
    # ==========================================

    connection = get_connection()
    cursor = connection.cursor()

    try:

        cursor.execute("""
            SELECT fichier_path
            FROM ressources
            WHERE id = %s
        """, (ressource_id,))

        ressource = cursor.fetchone()

    finally:
        cursor.close()
        connection.close()

    if not ressource:
        raise HTTPException(
            status_code=404,
            detail="Ressource introuvable"
        )

    fichier_path = ressource[0]

    # ==========================================
    # 2. SUPPRIMER LE PDF DE SUPABASE
    # ==========================================

    if fichier_path:

        delete_url = (
            f"{SUPABASE_URL}"
            f"/storage/v1/object/ressources/"
            f"{fichier_path}"
        )

        headers = {
            "apikey": SUPABASE_SECRET_KEY,
            "Authorization": f"Bearer {SUPABASE_SECRET_KEY}"
        }

        response_delete = httpx.delete(
            delete_url,
            headers=headers,
            timeout=60
        )

        print(
            "SUPABASE DELETE STATUS :",
            response_delete.status_code
        )

        print(
            "SUPABASE DELETE REPONSE :",
            response_delete.text
        )

        if response_delete.status_code >= 400:

            raise HTTPException(
                status_code=500,
                detail=(
                    "Impossible de supprimer le fichier "
                    "PDF de Supabase : "
                    f"{response_delete.text}"
                )
            )

    # ==========================================
    # 3. SUPPRIMER LA RESSOURCE DE POSTGRESQL
    # ==========================================

    connection = get_connection()
    cursor = connection.cursor()

    try:

        cursor.execute("""
            DELETE FROM ressources
            WHERE id = %s
        """, (ressource_id,))

        if cursor.rowcount == 0:

            connection.rollback()

            raise HTTPException(
                status_code=404,
                detail="Ressource introuvable"
            )

        connection.commit()

    except HTTPException:
        raise

    except Exception:

        connection.rollback()

        raise

    finally:
        cursor.close()
        connection.close()

    # ==========================================
    # 4. RÉPONSE
    # ==========================================

    return {
        "message": "Ressource supprimée avec succès",
        "ressource_id": ressource_id
    }
# ==========================================================
# LISTE DES UTILISATEURS
# ADMIN UNIQUEMENT
# ==========================================================

@app.get("/admin/users")
def get_users(
    token_data: dict = Depends(verify_admin)
):

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        SELECT
            u.id,
            u.nom,
            u.prenom,
            u.email,
            r.nom AS role,
            f.nom AS filiere,
            n.nom AS niveau,
            u.created_at
        FROM users u
        JOIN roles r
            ON u.role_id = r.id
        JOIN filieres f
            ON u.filiere_id = f.id
        JOIN niveaux n
            ON u.niveau_id = n.id
        ORDER BY u.created_at DESC;
    """)

    users = cursor.fetchall()

    cursor.close()
    connection.close()

    return [
        {
            "id": user[0],
            "nom": user[1],
            "prenom": user[2],
            "email": user[3],
            "role": user[4],
            "filiere": user[5],
            "niveau": user[6],
            "created_at": user[7]
        }
        for user in users
    ]

# ==========================================================
# MODIFIER UN UTILISATEUR
# ADMIN UNIQUEMENT
# ==========================================================

@app.put("/admin/users/{user_id}")
def update_user(
    user_id: int,
    nom: str = Form(...),
    prenom: str = Form(...),
    email: str = Form(...),
    filiere_id: int = Form(...),
    niveau_id: int = Form(...),
    token_data: dict = Depends(verify_admin)
):

    connection = get_connection()
    cursor = connection.cursor()

    # Vérifier que l'utilisateur existe
    cursor.execute("""
        SELECT id
        FROM users
        WHERE id = %s;
    """, (user_id,))

    user = cursor.fetchone()

    if user is None:
        cursor.close()
        connection.close()

        raise HTTPException(
            status_code=404,
            detail="Utilisateur introuvable"
        )

    # Vérifier que l'e-mail n'est pas déjà utilisé
    cursor.execute("""
        SELECT id
        FROM users
        WHERE email = %s
        AND id != %s;
    """, (email, user_id))

    existing_email = cursor.fetchone()

    if existing_email is not None:
        cursor.close()
        connection.close()

        raise HTTPException(
            status_code=400,
            detail="Cette adresse e-mail est déjà utilisée"
        )

    # Vérifier la filière
    cursor.execute("""
        SELECT id
        FROM filieres
        WHERE id = %s;
    """, (filiere_id,))

    if cursor.fetchone() is None:
        cursor.close()
        connection.close()

        raise HTTPException(
            status_code=400,
            detail="Filière invalide"
        )

    # Vérifier le niveau
    cursor.execute("""
        SELECT id
        FROM niveaux
        WHERE id = %s;
    """, (niveau_id,))

    if cursor.fetchone() is None:
        cursor.close()
        connection.close()

        raise HTTPException(
            status_code=400,
            detail="Niveau invalide"
        )

    # Mise à jour
    cursor.execute("""
        UPDATE users
        SET
            nom = %s,
            prenom = %s,
            email = %s,
            filiere_id = %s,
            niveau_id = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
    """, (
        nom,
        prenom,
        email,
        filiere_id,
        niveau_id,
        user_id
    ))

    connection.commit()

    cursor.close()
    connection.close()

    return {
        "message": "Utilisateur modifié avec succès",
        "user_id": user_id
    }


# ==========================================================
# SUPPRIMER UN UTILISATEUR
# ADMIN UNIQUEMENT
# ==========================================================

@app.delete("/admin/users/{user_id}")
def delete_user(
    user_id: int,
    token_data: dict = Depends(verify_admin)
):

    connection = get_connection()
    cursor = connection.cursor()

    # Empêcher l'administrateur de supprimer son propre compte
    current_user_id = int(token_data["sub"])

    if user_id == current_user_id:
        cursor.close()
        connection.close()

        raise HTTPException(
            status_code=400,
            detail="Un administrateur ne peut pas supprimer son propre compte"
        )

    # Vérifier que l'utilisateur existe
    cursor.execute("""
        SELECT id
        FROM users
        WHERE id = %s;
    """, (user_id,))

    user = cursor.fetchone()

    if user is None:
        cursor.close()
        connection.close()

        raise HTTPException(
            status_code=404,
            detail="Utilisateur introuvable"
        )

    # Supprimer l'utilisateur
    cursor.execute("""
        DELETE FROM users
        WHERE id = %s;
    """, (user_id,))

    connection.commit()

    cursor.close()
    connection.close()

    return {
        "message": "Utilisateur supprimé avec succès",
        "user_id": user_id
    }

# ==========================================================
# AJOUTER UNE MATIERE
# ADMIN UNIQUEMENT
# ==========================================================

@app.post("/admin/matieres")
def create_matiere(
    matiere: MatiereCreate,
    token_data: dict = Depends(verify_admin)
):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        # Vérifier que le niveau existe
        cursor.execute(
            "SELECT id FROM niveaux WHERE id = %s",
            (matiere.niveau_id,)
        )

        if not cursor.fetchone():
            raise HTTPException(
                status_code=404,
                detail="Niveau introuvable"
            )

        # Vérifier que le semestre existe
        cursor.execute(
            "SELECT id FROM semestres WHERE id = %s",
            (matiere.semestre_id,)
        )

        if not cursor.fetchone():
            raise HTTPException(
                status_code=404,
                detail="Semestre introuvable"
            )

        # Ajouter la matière
        cursor.execute("""
            INSERT INTO matieres (
                nom,
                niveau_id,
                semestre_id
            )
            VALUES (%s, %s, %s)
            RETURNING id
        """, (
            matiere.nom,
            matiere.niveau_id,
            matiere.semestre_id
        ))

        matiere_id = cursor.fetchone()[0]

        connection.commit()

        return {
            "message": "Matière ajoutée avec succès",
            "matiere_id": matiere_id,
            "nom": matiere.nom,
            "niveau_id": matiere.niveau_id,
            "semestre_id": matiere.semestre_id
        }

    except psycopg2.errors.UniqueViolation: # type: ignore
        connection.rollback()

        raise HTTPException(
            status_code=409,
            detail="Cette matière existe déjà dans ce niveau et ce semestre"
        )

    except HTTPException:
        connection.rollback()
        raise

    except Exception as e:
        connection.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'ajout de la matière : {str(e)}"
        )

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# MODIFIER UNE MATIERE
# ADMIN UNIQUEMENT
# ==========================================================

@app.put("/admin/matieres/{matiere_id}")
def update_matiere(
    matiere_id: int,
    matiere: MatiereCreate,
    token_data: dict = Depends(verify_admin)
):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        # Vérifier le niveau
        cursor.execute(
            "SELECT id FROM niveaux WHERE id = %s",
            (matiere.niveau_id,)
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=404,
                detail="Niveau introuvable"
            )

        # Vérifier le semestre
        cursor.execute(
            "SELECT id FROM semestres WHERE id = %s",
            (matiere.semestre_id,)
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=404,
                detail="Semestre introuvable"
            )

        # Modifier la matière
        cursor.execute("""
            UPDATE matieres
            SET
                nom = %s,
                niveau_id = %s,
                semestre_id = %s
            WHERE id = %s
        """, (
            matiere.nom,
            matiere.niveau_id,
            matiere.semestre_id,
            matiere_id
        ))

        if cursor.rowcount == 0:
            connection.rollback()
            raise HTTPException(
                status_code=404,
                detail="Matière introuvable"
            )

        connection.commit()

        return {
            "message": "Matière modifiée avec succès",
            "matiere_id": matiere_id,
            "nom": matiere.nom,
            "niveau_id": matiere.niveau_id,
            "semestre_id": matiere.semestre_id
        }

    except psycopg2.errors.UniqueViolation: # type: ignore
        connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="Cette matière existe déjà dans ce niveau et ce semestre"
        )

    except HTTPException:
        connection.rollback()
        raise

    except Exception as e:
        connection.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la modification : {str(e)}"
        )

    finally:
        cursor.close()
        connection.close()


# ==========================================================
# SUPPRIMER UNE MATIERE
# ADMIN UNIQUEMENT
# ==========================================================

@app.delete("/admin/matieres/{matiere_id}")
def delete_matiere(
    matiere_id: int,
    token_data: dict = Depends(verify_admin)
):

    connection = get_connection()
    cursor = connection.cursor()

    try:
        # Vérifier que la matière existe
        cursor.execute("""
            SELECT id, nom
            FROM matieres
            WHERE id = %s;
        """, (matiere_id,))

        matiere = cursor.fetchone()

        if matiere is None:
            raise HTTPException(
                status_code=404,
                detail="Matière introuvable"
            )

        # Vérifier si elle est utilisée
        cursor.execute("""
            SELECT COUNT(*)
            FROM ressources
            WHERE matiere_id = %s;
        """, (matiere_id,))

        nombre_ressources = cursor.fetchone()[0]

        if nombre_ressources > 0:
            raise HTTPException(
                status_code=400,
                detail="Impossible de supprimer cette matière car elle est utilisée par une ou plusieurs ressources"
            )

        # Supprimer
        cursor.execute("""
            DELETE FROM matieres
            WHERE id = %s;
        """, (matiere_id,))

        connection.commit()

        return {
            "message": "Matière supprimée avec succès",
            "matiere_id": matiere_id,
            "nom": matiere[1]
        }

    except HTTPException:
        connection.rollback()
        raise

    except Exception as e:
        connection.rollback()
        print("Erreur suppression matière :", e)

        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la suppression de la matière"
        )

    finally:
        cursor.close()
        connection.close()