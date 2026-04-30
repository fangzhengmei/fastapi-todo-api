import csv
import io
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import models, schemas, auth
from app.dependencies import get_db

router = APIRouter(tags=["Todos"])


# -------- CREATE -------- #
@router.post("/todos/", response_model=schemas.TodoOut)
def create_todo(
    todo: schemas.TodoCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    new_todo = models.Todo(**todo.dict(), owner_id=current_user.id)
    db.add(new_todo)
    db.commit()
    db.refresh(new_todo)
    return new_todo

# -------- LIST -------- #
@router.get("/todos/", response_model=List[schemas.TodoOut])
def get_todos(
    status: Optional[str] = Query(None),
    sort: Optional[str] = Query("id"),
    limit: int = Query(10, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    query = db.query(models.Todo).filter(models.Todo.owner_id == current_user.id)

    if status:
        query = query.filter(models.Todo.status == status)

    if sort in ["id", "title", "status"]:
        query = query.order_by(getattr(models.Todo, sort))

    return query.offset(offset).limit(limit).all()

# -------- GET ONE -------- #
@router.get("/todos/{todo_id}", response_model=schemas.TodoOut)
def get_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter_by(id=todo_id, owner_id=current_user.id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo

# -------- UPDATE -------- #
@router.put("/todos/{todo_id}", response_model=schemas.TodoOut)
def update_todo(
    todo_id: int,
    updated_data: schemas.TodoUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter_by(id=todo_id, owner_id=current_user.id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    for key, value in updated_data.dict(exclude_unset=True).items():
        setattr(todo, key, value)

    db.commit()
    db.refresh(todo)
    return todo

# -------- DELETE -------- #
@router.delete("/todos/{todo_id}")
def delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    todo = db.query(models.Todo).filter_by(id=todo_id, owner_id=current_user.id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    db.delete(todo)
    db.commit()
    return {"detail": "Todo deleted"}


# -------- CSV IMPORT HELPERS -------- #
def validate_todo_row(row: Dict[str, Any], row_number: int) -> Dict[str, Any]:
    """Validate a single row from CSV file."""
    errors = []
    
    # Check for required fields
    if not row.get("title") or not str(row.get("title")).strip():
        errors.append("Title is required")
    
    # Validate status if provided
    status = row.get("status", "not_done")
    valid_statuses = ["not_done", "done"]
    if status and status not in valid_statuses:
        errors.append(f"Status must be one of: {', '.join(valid_statuses)}")
    
    # Validate title length
    title = str(row.get("title", "")).strip()
    if len(title) > 255:
        errors.append("Title must be 255 characters or less")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "row_number": row_number,
        "data": {
            "title": title if title else None,
            "description": str(row.get("description", "")).strip() if row.get("description") else None,
            "status": status if status in valid_statuses else "not_done"
        }
    }


# -------- CSV IMPORT -------- #
@router.post("/todos/import/", response_model=Dict[str, Any])
def import_todos_from_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Import todos from a CSV file.
    
    Expected CSV format:
    - title: required
    - description: optional
    - status: optional (not_done or done, default: not_done)
    """
    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV file")
    
    # Read and parse CSV
    try:
        contents = file.file.read()
        # Try to decode with UTF-8, fallback to latin-1
        try:
            decoded = contents.decode('utf-8')
        except UnicodeDecodeError:
            decoded = contents.decode('latin-1')
        
        csv_reader = csv.DictReader(io.StringIO(decoded))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read CSV file: {str(e)}")
    
    # Validate CSV headers
    if not csv_reader.fieldnames or "title" not in csv_reader.fieldnames:
        raise HTTPException(
            status_code=400, 
            detail="CSV file must have at least a 'title' column"
        )
    
    # Process each row
    successful = []
    failed = []
    row_number = 1
    
    for row in csv_reader:
        row_number += 1  # Start from 2 because header is row 1
        
        # Validate the row
        validation = validate_todo_row(row, row_number)
        
        if validation["valid"]:
            try:
                # Create the todo
                todo_data = validation["data"]
                new_todo = models.Todo(
                    title=todo_data["title"],
                    description=todo_data["description"],
                    status=todo_data["status"],
                    owner_id=current_user.id
                )
                db.add(new_todo)
                db.flush()  # Get the ID without committing
                
                successful.append({
                    "row_number": row_number,
                    "title": todo_data["title"],
                    "id": new_todo.id
                })
            except Exception as e:
                failed.append({
                    "row_number": row_number,
                    "title": row.get("title", ""),
                    "errors": [f"Database error: {str(e)}"]
                })
        else:
            failed.append({
                "row_number": row_number,
                "title": row.get("title", ""),
                "errors": validation["errors"]
            })
    
    # Commit all successful todos
    db.commit()
    
    return {
        "total": len(successful) + len(failed),
        "successful": len(successful),
        "failed": len(failed),
        "successful_items": successful,
        "failed_items": failed
    }


# -------- CSV EXPORT -------- #
@router.get("/todos/export/")
def export_todos_to_csv(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Export todos to a CSV file.
    
    CSV format:
    - id: Todo ID
    - title: Todo title
    - description: Todo description
    - status: Todo status (not_done or done)
    """
    # Get todos from database
    query = db.query(models.Todo).filter(models.Todo.owner_id == current_user.id)
    
    if status:
        query = query.filter(models.Todo.status == status)
    
    todos = query.all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['id', 'title', 'description', 'status'])
    
    # Write data rows
    for todo in todos:
        writer.writerow([
            todo.id,
            todo.title,
            todo.description if todo.description else "",
            todo.status
        ])
    
    # Reset file pointer to beginning
    output.seek(0)
    
    # Create streaming response
    response = StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv"
    )
    
    # Set headers for file download
    response.headers["Content-Disposition"] = "attachment; filename=todos_export.csv"
    
    return response