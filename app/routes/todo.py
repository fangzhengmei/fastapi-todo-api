import csv
import io
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app import models, schemas, auth
from app.dependencies import get_db

# 常量定义
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB
VALID_STATUSES = ["not_done", "done"]

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
def validate_todo_row(row: Dict[str, Any], row_number: int, has_status_column: bool = False) -> Dict[str, Any]:
    """Validate a single row from CSV file.
    
    Args:
        row: CSV row data
        row_number: Row number for error reporting
        has_status_column: Whether the CSV has a status column
    """
    errors = []
    
    # Check for required fields
    if not row.get("title") or not str(row.get("title")).strip():
        errors.append("Title is required")
    
    # Validate status
    if has_status_column:
        # CSV has status column - check the value
        status = row.get("status")
        
        if status is None or str(status).strip() == "":
            # Status column exists but value is empty - this is an error
            errors.append("Status is required when status column is present")
        else:
            # Status column exists and has a value - validate it
            status = str(status).strip()
            if status not in VALID_STATUSES:
                errors.append(f"Status must be one of: {', '.join(VALID_STATUSES)}")
    else:
        # CSV does not have status column - use default value
        status = "not_done"
    
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
            "status": status if status in VALID_STATUSES else "not_done"
        }
    }


# -------- CSV IMPORT -------- #
@router.post("/todos/import/", response_model=schemas.TodoImportResponse)
def import_todos_from_csv(
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """Import todos from a CSV file.
    
    Expected CSV format:
    - title: required
    - description: optional
    - status: optional (not_done or done, default: not_done)
    
    Parameters:
    - dry_run: If true, only validate the file without saving to database
    """
    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV file")
    
    # Read file content
    try:
        contents = file.file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")
    
    # Validate file size (1MB limit) - outside exception handling for clarity
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, 
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024 * 1024)}MB"
        )
    
    # Decode and parse CSV
    try:
        # Try to decode with UTF-8, fallback to latin-1
        try:
            decoded = contents.decode('utf-8')
            # Strip UTF-8 BOM if present (Excel exported CSV often has this)
            if decoded.startswith('\ufeff'):
                decoded = decoded[1:]
        except UnicodeDecodeError:
            decoded = contents.decode('latin-1')
        
        csv_reader = csv.DictReader(io.StringIO(decoded))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV file: {str(e)}")
    
    # Validate CSV headers
    if not csv_reader.fieldnames or "title" not in csv_reader.fieldnames:
        raise HTTPException(
            status_code=400, 
            detail="CSV file must have at least a 'title' column"
        )
    
    # Check if CSV has status column
    has_status_column = "status" in csv_reader.fieldnames
    
    # Process each row
    successful = []
    failed = []
    row_number = 1
    
    for row in csv_reader:
        row_number += 1  # Start from 2 because header is row 1
        
        # Validate the row
        validation = validate_todo_row(row, row_number, has_status_column)
        
        if validation["valid"]:
            if dry_run:
                # Dry run: just add to successful list without creating in DB
                successful.append({
                    "row_number": row_number,
                    "title": validation["data"]["title"],
                    "id": None  # No ID in dry run mode
                })
            else:
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
    
    # Commit all successful todos (only if not dry run)
    if not dry_run:
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
    # Validate status parameter if provided
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid status value. Must be one of: {', '.join(VALID_STATUSES)}"
        )
    
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