import sys, traceback
# 先手动运行迁移
try:
    from alembic.config import Config
    from alembic import command
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")
    print(">>> Migration OK", flush=True)
except Exception as e:
    print(f">>> Migration FAILED: {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)

# 再启动 uvicorn
try:
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8080, log_level="info", reload=False)
except SystemExit as e:
    print(f">>> SystemExit: code={e.code}", flush=True)
    traceback.print_exc()
except Exception as e:
    print(f">>> EXCEPTION: {type(e).__name__}: {e}", flush=True)
    traceback.print_exc()
