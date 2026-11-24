import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import settings
from app.database import init_db, AsyncSessionLocal

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    logger.info("Starting CodeWeave backend...")

    # 1. Initialise database and ensure seed user exists
    try:
        await init_db()
        logger.info("Database initialised successfully")

        from app.models.user import User

        async with AsyncSessionLocal() as session:
            existing = await session.execute(
                select(User).where(User.id == 1)
            )

            if not existing.scalar_one_or_none():
                session.add(
                    User(
                        id=1,
                        github_id=0,
                        username="dev-user",
                        email="dev@codeweave.local",
                    )
                )
                await session.commit()
                logger.info("Seed development user created (id=1)")
            else:
                logger.info("Seed development user already exists")

    except Exception:
        logger.exception("Database initialisation failed")

    # 2. Pre-load embedding model
    try:
        from app.services.embeddings import EmbeddingService

        EmbeddingService.get_instance()
        logger.info("Embedding model loaded successfully")

    except Exception:
        logger.exception("Embedding model loading failed (non-fatal)")

    # 3. Initialise Redis cache
    try:
        from app.services.cache import init_cache

        init_cache(settings.REDIS_URL)
        logger.info("Redis cache initialised successfully")

    except Exception:
        logger.exception("Redis initialisation failed (caching disabled)")

    # 4. Initialise rate limiter
    try:
        from app.services.rate_limiter import init_rate_limiter

        init_rate_limiter(settings.REDIS_URL)
        logger.info("Rate limiter initialised successfully")

    except Exception:
        logger.exception("Rate limiter initialisation failed (disabled)")

    logger.info("CodeWeave backend startup sequence completed")

    yield

    # Shutdown
    logger.info("Shutting down CodeWeave backend...")


app = FastAPI(
    title=settings.APP_NAME,
    description="AI-Powered Autonomous Code Engineering Platform",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# API Routers
from app.api import auth, repos  # noqa: E402
from app.api import chat  # noqa: E402
from app.api import agent  # noqa: E402

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(repos.router, prefix="/api/repos", tags=["Repositories"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])


@app.get("/health", tags=["Health"])
async def health_check():
    """Check the availability of application services."""

    from app.services.cache import get_cache
    from app.services.embeddings import EmbeddingService

    # Check Redis availability
    redis_ok = False
    try:
        cache = get_cache()
        redis_ok = await cache.ping()
    except Exception as e:
        logger.debug("Redis health check failed: %s", e)

    # Check embedding model availability
    embed_ok = False
    try:
        EmbeddingService.get_instance()
        embed_ok = True
    except Exception as e:
        logger.debug("Embedding health check failed: %s", e)

    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": "0.1.0",
        "services": {
            "redis": "ok" if redis_ok else "unavailable",
            "embeddings": "ok" if embed_ok else "unavailable",
            "llm": (
                "configured"
                if settings.OPENROUTER_API_KEY
                else "not configured"
            ),
        },
    }
