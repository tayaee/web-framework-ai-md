from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

app = FastAPI()


class ConvertRequest(BaseModel):
    input_temperature: float = Field(..., description="The temperature value to convert")
    input_unit: Literal["C", "F"] = Field(..., description="The unit of the input temperature: 'C' for Celsius or 'F' for Fahrenheit")


class ConvertResponse(BaseModel):
    output_temperature: float = Field(..., description="The converted temperature value")
    output_unit: str = Field(..., description="The unit of the converted temperature: 'C' for Celsius or 'F' for Fahrenheit")


@app.post("/v1/convert")
def convert_temperature(request: ConvertRequest) -> ConvertResponse:
    if request.input_unit == "C":
        converted = request.input_temperature * 9 / 5 + 32
        output_unit = "F"
    else:
        converted = (request.input_temperature - 32) * 5 / 9
        output_unit = "C"
    return ConvertResponse(output_temperature=converted, output_unit=output_unit)