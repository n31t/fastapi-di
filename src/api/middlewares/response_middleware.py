"""
Response middleware for automatic standardized API response wrapping.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import json
import math
from typing import Any

from src.core.logging import get_logger

logger = get_logger(__name__)


class StandardResponseMiddleware(BaseHTTPMiddleware):
    """
    Middleware that wraps all successful JSON responses in a standard format.

    For paginated responses (with 'total', 'limit', 'offset'), it creates:
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Skip OpenAPI/docs endpoints
        if request.url.path in ["/openapi.json", "/docs", "/redoc"]:
            return response

        # Only process successful JSON responses (200-299 status codes)
        if not (200 <= response.status_code < 300):
            return response

        # Only process JSON responses
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        # Skip if response is already wrapped (has 'status' field)
        try:
            # Read response body
            body = b""
            async for chunk in response.body_iterator:
                body += chunk

            if not body:
                return response

            data = json.loads(body.decode())

            # If already wrapped with 'status', return as-is
            if isinstance(data, dict) and "status" in data:
                # Create clean headers without content-length
                headers = {k: v for k, v in response.headers.items()
                          if k.lower() not in ["content-length", "transfer-encoding"]}
                return JSONResponse(
                    content=data,
                    status_code=response.status_code,
                    headers=headers
                )

            # Wrap the response
            wrapped_data = self._wrap_response(data)

            # Create clean headers without content-length (JSONResponse will set it correctly)
            # headers = {k: v for k, v in response.headers.items()
            #           if k.lower() not in ["content-length", "transfer-encoding"]}

            new_response = JSONResponse(
                content=wrapped_data,
                status_code=response.status_code,
            )

            # Copy headers from original response to new response, preserving multiple headers (like Set-Cookie)
            # JSONResponse creates its own Content-Length and Content-Type, so we skip those
            for key, value in response.headers.items():
                if key.lower() in ["content-length", "content-type", "transfer-encoding"]:
                    continue
                new_response.headers.append(key, value)

            return new_response

        except Exception as e:

            logger.error(
                "response_middleware_error",
                error=str(e),
                path=request.url.path
            )
            # Return original response if wrapping fails
            return response

    def _wrap_response(self, data: Any) -> dict:
        """
        Wrap response data in standard format.

        Detects pagination patterns and formats accordingly.
        """
        if not isinstance(data, dict):
            return {
                "data": data
            }

        # Check for pagination pattern (has total, limit, offset)
        if self._is_paginated_response(data):
            return self._format_paginated_response(data)

        # Regular response
        return {
            "data": data
        }

    def _is_paginated_response(self, data: dict) -> bool:
        """Check if response follows pagination pattern."""
        return (
            "total" in data and
            isinstance(data.get("total"), int) and
            ("limit" in data or "offset" in data)
        )

    def _format_paginated_response(self, data: dict) -> dict:
        """
        Format paginated response with proper structure.

        Converts from:
        {
            "reviews": [...],
            "total": 100,
            "limit": 10,
            "offset": 0
        }

        To:
        {
            "data": {
                "reviews": [...],  // keeps original key
                "pagination": {
                    "page": 1,
                    "pageSize": 10,
                    "totalReviews": 100,  // or totalItems
                    "totalPages": 10
                }
            }
        }
        """
        total = data.get("total", 0)
        limit = data.get("limit", 10)
        offset = data.get("offset", 0)

        page = (offset // limit) + 1 if limit > 0 else 1
        total_pages = math.ceil(total / limit) if limit > 0 else 0

        # Find the items key (reviews, cities, items, etc.)
        items_key = None
        for key in data.keys():
            if key not in ["total", "limit", "offset"] and isinstance(data[key], list):
                items_key = key
                break

        # Build response data
        response_data = {}

        # Add items with their original key
        if items_key:
            response_data[items_key] = data[items_key]

        # Add pagination metadata
        response_data["pagination"] = {
            "page": page,
            "pageSize": limit,
            f"total{items_key.capitalize() if items_key else 'Items'}": total,
            "totalPages": total_pages
        }

        return {
            "data": response_data
        }
