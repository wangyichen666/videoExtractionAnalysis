from fastapi import FastAPI


def create_app(lifespan) -> FastAPI:
    # 原版完整应用按需加载，独立提取服务不依赖 RAG 或本地 ASR。
    from .routers import note, provider, model, config, chat
    app = FastAPI(title="BiliNote", lifespan=lifespan)
    for router in (note.router, provider.router, model.router, config.router, chat.router):
        app.include_router(router, prefix="/api")
    return app
