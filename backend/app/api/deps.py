"""Shared route dependencies: the app's Runtime and a business-ID path parameter."""

from typing import Annotated

from fastapi import Depends, Path, Request

from app.services.runtime import Runtime


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]
BusinessId = Annotated[str, Path(description="Business ID, e.g. maya-corner-store", max_length=63)]
