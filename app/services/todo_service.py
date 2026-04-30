from fastapi import HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app import models, schemas


class TodoService:
    @staticmethod
    def create_todo(db: Session, todo_data: schemas.TodoCreate, user_id: int) -> models.Todo:
        new_todo = models.Todo(**todo_data.dict(), owner_id=user_id)
        db.add(new_todo)
        db.commit()
        db.refresh(new_todo)
        return new_todo

    @staticmethod
    def get_todos(
        db: Session,
        user_id: int,
        status: Optional[str] = None,
        sort: str = "id",
        limit: int = 10,
        offset: int = 0
    ) -> List[models.Todo]:
        query = db.query(models.Todo).filter(models.Todo.owner_id == user_id)

        if status:
            query = query.filter(models.Todo.status == status)

        if sort in ["id", "title", "status"]:
            query = query.order_by(getattr(models.Todo, sort))

        return query.offset(offset).limit(limit).all()

    @staticmethod
    def get_todo_by_id(db: Session, todo_id: int, user_id: int) -> models.Todo:
        todo = db.query(models.Todo).filter_by(id=todo_id, owner_id=user_id).first()
        if not todo:
            raise HTTPException(status_code=404, detail="Todo not found")
        return todo

    @staticmethod
    def update_todo(
        db: Session,
        todo_id: int,
        user_id: int,
        update_data: schemas.TodoUpdate
    ) -> models.Todo:
        todo = TodoService.get_todo_by_id(db, todo_id, user_id)

        for key, value in update_data.dict(exclude_unset=True).items():
            setattr(todo, key, value)

        db.commit()
        db.refresh(todo)
        return todo

    @staticmethod
    def delete_todo(db: Session, todo_id: int, user_id: int) -> None:
        todo = TodoService.get_todo_by_id(db, todo_id, user_id)

        db.delete(todo)
        db.commit()
