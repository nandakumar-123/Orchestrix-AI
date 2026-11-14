from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response payload schema."""

    status: str = Field(..., description="Service status indicator")
    app: str = Field(..., description="Application name")
    environment: str = Field(..., description="Current environment")
    version: str = Field(..., description="API version")
