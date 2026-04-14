"""Pydantic-compatible ObjectId type for MongoDB documents.

Drop-in replacement for a custom PyObjectId type.
"""

from typing import Annotated, Any

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema


class _ObjectIdAnnotation:
    """Pydantic v2 annotation for bson.ObjectId fields."""

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        def validate(value: Any) -> ObjectId:
            if isinstance(value, ObjectId):
                return value
            if isinstance(value, str):
                try:
                    return ObjectId(value)
                except InvalidId as e:
                    raise ValueError(str(e)) from e
            raise ValueError(f"Cannot convert {type(value)} to ObjectId")

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.to_string_ser_schema(),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        return {"type": "string", "format": "objectid"}


PyObjectId = Annotated[ObjectId, _ObjectIdAnnotation]
