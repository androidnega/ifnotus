"""Pagination helpers."""

from typing import TypeVar

from app.schemas.common import PaginatedResponse, PaginationParams

T = TypeVar("T")


def paginate(items: list[T], total: int, params: PaginationParams) -> PaginatedResponse[T]:
    """Build a paginated response from items and total count."""
    return PaginatedResponse.create(items, total, params)
