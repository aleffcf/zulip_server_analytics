import os
import secrets
import asyncio
from dotenv import load_dotenv

from datetime import datetime, timedelta, timezone

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import jwt
import bcrypt
from fastapi import FastAPI, Depends, HTTPException, status, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from sqlalchemy import MetaData, select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Carrega o arquivo .env
load_dotenv()

# Variaveis de conexao com o Bando de Dados
pg_user = os.getenv("DB_USER")
# pg_password = os.getenv("DB_PASSWORD")
pg_host = os.getenv("DB_HOST")
pg_port = os.getenv("DB_PORT")
pg_name = os.getenv("DB_NAME")

# Conexao com o banco de dados
# engine = create_async_engine(f"postgresql+asyncpg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_name}")

engine = create_async_engine(f"postgresql+asyncpg://{pg_user}@{pg_host}:{pg_port}/{pg_name}", connect_args={"host":"/var/run/postgresql/.s.PGSQL.5432"})


# Criando ponteiro para manuseio do banco de dados
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

# Carregando Metadata e Tabelas do Zulip Globalmente
metadata = MetaData()
realms_table = None
users_table = None
messages_table = None

# Configuracao de autenticacao
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

bearer_scheme = HTTPBearer()

limiter = Limiter(key_func=get_remote_address)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global realms_table
    global users_table
    global messages_table
    global clients_table

    async with engine.begin() as conn:
       await conn.run_sync(metadata.reflect, only=["zerver_realm", "zerver_userprofile", "zerver_message", "zerver_client"])

    realms_table = metadata.tables["zerver_realm"]
    users_table = metadata.tables["zerver_userprofile"]
    messages_table = metadata.tables["zerver_message"]
    clients_table = metadata.tables["zerver_client"]

    # Lógica de Startup (ex: testar conexão com o DB)
    yield
    # Lógica de Shutdown (ex: limpar recursos, encerrar conexões)
    await engine.dispose()

# Instanciando a classe FastAPI
app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: em dev, liberar tudo é aceitável. Em produção, troque "*" pela URL
# real do seu app/painel (ou remova o middleware, já que apps nativos não
# são afetados por CORS de qualquer forma).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Schemas de dados (Payloads)
class LoginPayload(BaseModel):
    api_key: str

# Funcao de validacao da conexao com o banco
async def get_db():
    async with SessionLocal() as db:
        yield db

# Funcao de validacao do token jwt
async def verify_jwt_token(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "O token de acesso expirou.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "Token de autenticacao invalido."
        )

# Inicio das rotas

# Rota HOME
@app.get("/")
async def hello():
    return {'res':'Hello World!'}

# Rota para Gerar/Renovar o Token JWT seguro informando a chave mestre
@app.post("/token")
@limiter.limit("5/minute")
async def login_for_access_token(request: Request, body: LoginPayload):
    if body.api_key != ADMIN_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chave de API inválida.",
        )
    
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode = {"sub": "admin_reporter", "exp": expire}
    access_token = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    return {"access_token": access_token, "token_type": "bearer", "expires_in_hours": ACCESS_TOKEN_EXPIRE_HOURS}

# Rotas de Realm
@app.get("/all_realms")
async def get_all_realms(db: AsyncSession = Depends(get_db), user: dict = Depends(verify_jwt_token)):
    # Constrói o select na tabela refletida no lifespan
    stmt = select(
        realms_table.c.id,
        realms_table.c.name,
        realms_table.c.string_id,
        realms_table.c.description
    )
    
    # Executa a query usando a sessão injetada pelo FastAPI
    result = await db.execute(stmt)
    rows = result.all()
    
    # Transforma os resultados em uma lista de dicionários para serializar em JSON
    realms_list = [dict(row._mapping) for row in rows]
    
    return {'res': realms_list }

@app.get("/server_analytics")
async def get_server_analytics(db: AsyncSession = Depends(get_db), user: dict = Depends(verify_jwt_token)):
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=15)

    counts_stmt = select(
        select(func.count()).select_from(realms_table).scalar_subquery(),
        select(func.count()).select_from(users_table).scalar_subquery(),
        select(func.count()).select_from(messages_table).scalar_subquery(),
        select(func.count()).select_from(users_table).where(users_table.c.last_login >= cutoff_date).scalar_subquery(),
        select(func.count()).select_from(messages_table).where(messages_table.c.date_sent >= cutoff_date).scalar_subquery(),
    )
    
    clients_stmt = (
        select(
            clients_table.c.name, 
            func.count(messages_table.c.id).label("total")
        )
        .select_from(messages_table)
        .join(clients_table, messages_table.c.sending_client_id == clients_table.c.id)
        .group_by(clients_table.c.name)
    )

    counts_result = (await db.execute(counts_stmt)).tuples().one()
    clients_result = (await db.execute(clients_stmt)).all()

    total_realms, total_users, total_messages, active_users_15_days, messages_15_days = counts_result

    clients_count = {name: count for name, count in clients_result}

    return {
        'data': {
            'total_realms': total_realms,
            'total_users': total_users,
            'total_messages': total_messages,
            'active_users_15_days': active_users_15_days,
            'messages_15_days': messages_15_days,
            'clients_count_connection': clients_count
        }
    }

@app.get("/status_realm")
async def get_realms_with_users(db: AsyncSession = Depends(get_db), user: dict = Depends(verify_jwt_token)):
    # 1. Busca os Realms
    stmt_realms = select(
        realms_table.c.id,
        realms_table.c.name,
        realms_table.c.string_id
    )
    result_realms = await db.execute(stmt_realms)
    realms = [dict(row._mapping) for row in result_realms.all()]

    # 2. Busca os Usuários
    stmt_users = select(
        users_table.c.id,
        users_table.c.email,
        users_table.c.full_name,
        users_table.c.is_active,
        users_table.c.realm_id
    )
    result_users = await db.execute(stmt_users)
    users = [dict(row._mapping) for row in result_users.all()]

    stmt_messages = select(
        messages_table
    )

    result_messages = await db.execute(stmt_messages)
    messages = [dict(row._mapping) for row in result_messages.all()]

    # 3. Agrupa os usuários por realm_id em um dicionário para busca rápida O(1)
    users_by_realm = {}
    for u in users:
        r_id = u["realm_id"]
        if r_id not in users_by_realm:
            users_by_realm[r_id] = []
        users_by_realm[r_id].append(u)

    # 4. Injeta a lista de usuários dentro do respectivo Realm
    for r in realms:
        # Se não houver usuários, retorna uma lista vazia []
        r["users"] = users_by_realm.get(r["id"], [])

    return {'res': realms, 'messages': len(messages)}
