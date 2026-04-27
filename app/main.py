from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import Base, engine
from app.routes import user, todo
from app.routes.todo import auto_cleanup_all_users_trash

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False

scheduler = None


def start_scheduler():
    """Start the background scheduler for auto-cleanup tasks."""
    global scheduler
    
    if not APSCHEDULER_AVAILABLE:
        print("Warning: APScheduler not installed. Auto-cleanup scheduler disabled.")
        print("Install it with: pip install apscheduler")
        return
    
    if scheduler is not None and scheduler.running:
        return
    
    scheduler = BackgroundScheduler()
    
    scheduler.add_job(
        auto_cleanup_all_users_trash,
        trigger=IntervalTrigger(hours=24),
        id="trash_auto_cleanup",
        name="Auto-cleanup expired trash items",
        replace_existing=True
    )
    
    scheduler.start()
    print("Auto-cleanup scheduler started. Running every 24 hours.")


def stop_scheduler():
    """Stop the background scheduler."""
    global scheduler
    if scheduler is not None and scheduler.running:
        scheduler.shutdown()
        print("Auto-cleanup scheduler stopped.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: startup and shutdown events."""
    Base.metadata.create_all(bind=engine)
    
    start_scheduler()
    
    yield
    
    stop_scheduler()


app = FastAPI(
    title="To-Do List API",
    lifespan=lifespan
)

app.include_router(user.router)
app.include_router(todo.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Welcome to the To-Do List API!"}


@app.get("/health/scheduler")
def get_scheduler_status():
    """Get the status of the auto-cleanup scheduler."""
    global scheduler
    
    if not APSCHEDULER_AVAILABLE:
        return {
            "status": "unavailable",
            "message": "APScheduler not installed. Install with: pip install apscheduler"
        }
    
    if scheduler is None:
        return {
            "status": "not_initialized",
            "message": "Scheduler not initialized"
        }
    
    if scheduler.running:
        jobs = []
        for job in scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None
            })
        
        return {
            "status": "running",
            "message": "Auto-cleanup scheduler is running",
            "jobs": jobs
        }
    else:
        return {
            "status": "stopped",
            "message": "Scheduler is not running"
        }