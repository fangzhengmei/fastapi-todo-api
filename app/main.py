from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import Base, engine
from app.routes import user, todo, share

app = FastAPI(title="To-Do List API", version="1.1.0")

# Create all tables
Base.metadata.create_all(bind=engine)

# Include routers
app.include_router(user.router)
app.include_router(todo.router)
app.include_router(share.router)

# CORS Middleware (if using frontend or testing from browser tools)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development only; restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {
        "message": "Welcome to the To-Do List API!",
        "version": "1.1.0",
        "features": [
            "User authentication",
            "Todo CRUD operations",
            "Share todos with users",
            "Create shareable links",
            "Permission management"
        ]
    }