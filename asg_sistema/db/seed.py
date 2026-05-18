from sqlalchemy.orm import Session
from passlib.context import CryptContext

from asg_sistema.db.conexao import SessionLocal
from asg_sistema.db.models import Usuario

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


def gerar_hash_senha(senha: str) -> str:
    return pwd_context.hash(str(senha))


def criar_usuario(
    db: Session,
    nome: str,
    email: str,
    senha: str,
    papel: str,
):
    usuario_existente = (
        db.query(Usuario)
        .filter(Usuario.email == email)
        .first()
    )

    if usuario_existente:
        print(f"Usuário já existe: {email}")
        return

    usuario = Usuario(
        nome=nome,
        cargo=papel,
        email=email,
        senha_hash=gerar_hash_senha(senha),
        papel=papel,
    )

    db.add(usuario)

    print(f"{papel} criado com sucesso.")


def executar_seed():
    db: Session = SessionLocal()

    try:
        criar_usuario(
            db=db,
            nome="Admin",
            email="admin@gmail.com",
            senha="admin123",
            papel="ADMIN",
        )

        criar_usuario(
            db=db,
            nome="Usuario",
            email="user@gmail.com",
            senha="user123",
            papel="USER",
        )

        db.commit()

        print("Seed executada com sucesso.")

    except Exception as e:
        db.rollback()
        print(f"Erro ao executar seed: {e}")

    finally:
        db.close()


if __name__ == "__main__":
    executar_seed()