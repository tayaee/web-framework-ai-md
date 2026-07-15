from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class TemperatureRequest(BaseModel):
    temperature: float
    type: str

class TemperatureResponse(BaseModel):
    result: float

@app.post("/convert")
def convert(req: TemperatureRequest):
    if req.type == "C":
        result = req.temperature * 9/5 + 32
    elif req.type == "F":
        result = (req.temperature - 32) * 5/9
    else:
        result = None
    return TemperatureResponse(result=result)