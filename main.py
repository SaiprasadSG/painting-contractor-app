from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
import pandas as pd
from fastapi.responses import JSONResponse, FileResponse
import os
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from datetime import datetime
import tempfile

app = FastAPI()

# Serve frontend static files
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update to specific domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB connection
MONGO_URI = os.getenv("DATABASE_URL", "mongodb://localhost:27017")
client = AsyncIOMotorClient(MONGO_URI)
db = client["painting_contractor"]
sites_collection = db["sites"]
materials_collection = db["materials"]
labour_collection = db["labour"]
logs_collection = db["logs"]

# Models
class Client(BaseModel):
    name: str
    phone: str
    email: str

class Site(BaseModel):
    name: str
    client: Client
    address: str
    startDate: str
    status: str

class Material(BaseModel):
    name: str
    quantity: int
    costPerUnit: float

class Labour(BaseModel):
    name: str
    ratePerDay: float

class DailyLog(BaseModel):
    siteId: str
    date: str
    materials: list[dict]  # {materialId: str, quantity: int}
    labour: list[dict]     # {labourId: str, count: int}
    notes: str

# Helpers
def site_helper(site) -> dict:
    return {
        "_id": str(site["_id"]),
        "name": site["name"],
        "client": site["client"],
        "address": site["address"],
        "startDate": site["startDate"],
        "status": site["status"]
    }

def material_helper(material) -> dict:
    return {
        "_id": str(material["_id"]),
        "name": material["name"],
        "quantity": material["quantity"],
        "costPerUnit": material["costPerUnit"]
    }

def labour_helper(labour) -> dict:
    return {
        "_id": str(labour["_id"]),
        "name": labour["name"],
        "ratePerDay": labour["ratePerDay"]
    }

def log_helper(log) -> dict:
    return {
        "_id": str(log["_id"]),
        "siteId": str(log["siteId"]),
        "date": log["date"],
        "materials": log["materials"],
        "labour": log["labour"],
        "notes": log["notes"],
        "totalCost": log.get("totalCost", 0)
    }

# Sites Endpoints
@app.get("/api/sites")
async def get_sites():
    sites = []
    async for site in sites_collection.find():
        sites.append(site_helper(site))
    return sites

@app.post("/api/sites")
async def create_site(site: Site):
    site_dict = site.dict()
    result = await sites_collection.insert_one(site_dict)
    new_site = await sites_collection.find_one({"_id": result.inserted_id})
    return site_helper(new_site)

@app.put("/api/sites/{id}")
async def update_site(id: str, site: Site):
    result = await sites_collection.update_one(
        {"_id": ObjectId(id)},
        {"$set": site.dict()}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Site not found")
    updated_site = await sites_collection.find_one({"_id": ObjectId(id)})
    return site_helper(updated_site)

@app.delete("/api/sites/{id}")
async def delete_site(id: str):
    result = await sites_collection.delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Site not found")
    return {"message": "Site deleted"}

# Materials Endpoints
@app.get("/api/materials")
async def get_materials():
    materials = []
    async for material in materials_collection.find():
        materials.append(material_helper(material))
    return materials

@app.post("/api/materials")
async def create_material(material: Material):
    material_dict = material.dict()
    result = await materials_collection.insert_one(material_dict)
    new_material = await materials_collection.find_one({"_id": result.inserted_id})
    return material_helper(new_material)

@app.delete("/api/materials/{id}")
async def delete_material(id: str):
    result = await materials_collection.delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Material not found")
    return {"message": "Material deleted"}

# Labour Endpoints
@app.get("/api/labour")
async def get_labour():
    labour = []
    async for worker in labour_collection.find():
        labour.append(labour_helper(worker))
    return labour

@app.post("/api/labour")
async def create_labour(labour: Labour):
    labour_dict = labour.dict()
    result = await labour_collection.insert_one(labour_dict)
    new_labour = await labour_collection.find_one({"_id": result.inserted_id})
    return labour_helper(new_labour)

@app.delete("/api/labour/{id}")
async def delete_labour(id: str):
    result = await labour_collection.delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Labour not found")
    return {"message": "Labour deleted"}

# Daily Logs Endpoints
@app.post("/api/logs")
async def create_log(log: DailyLog):
    log_dict = log.dict()
    # Calculate total cost
    total_cost = 0
    # Material cost
    for mat in log.materials:
        material = await materials_collection.find_one({"_id": ObjectId(mat["materialId"])})
        if material:
            total_cost += material["costPerUnit"] * mat["quantity"]
            # Update central inventory
            await materials_collection.update_one(
                {"_id": ObjectId(mat["materialId"])},
                {"$inc": {"quantity": -mat["quantity"]}}
            )
    # Labour cost
    for lab in log.labour:
        worker = await labour_collection.find_one({"_id": ObjectId(lab["labourId"])})
        if worker:
            total_cost += worker["ratePerDay"] * lab["count"]
    log_dict["totalCost"] = total_cost
    result = await logs_collection.insert_one(log_dict)
    new_log = await logs_collection.find_one({"_id": result.inserted_id})
    return log_helper(new_log)

@app.get("/api/logs/site/{site_id}")
async def get_logs_for_site(site_id: str):
    logs = []
    async for log in logs_collection.find({"siteId": site_id}):
        logs.append(log_helper(log))
    return logs

# Reports Endpoint
@app.get("/api/reports/sites")
async def get_site_report():
    sites = []
    async for site in sites_collection.find():
        site_data = site_helper(site)
        logs = []
        async for log in logs_collection.find({"siteId": str(site["_id"])}):
            logs.append(log_helper(log))
        site_data["logs"] = logs
        site_data["totalCost"] = sum(log["totalCost"] for log in logs)
        sites.append(site_data)
    df = pd.DataFrame(sites)
    return JSONResponse(content=df.to_dict(orient="records"))

@app.get("/api/reports/sites/csv")
async def get_site_report_csv():
    sites = []
    async for site in sites_collection.find():
        site_data = site_helper(site)
        logs = []
        async for log in logs_collection.find({"siteId": str(site["_id"])}):
            logs.append(log_helper(log))
        site_data["logs"] = logs
        site_data["totalCost"] = sum(log["totalCost"] for log in logs)
        sites.append(site_data)
    df = pd.DataFrame(sites)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        df.to_csv(tmp.name, index=False)
        return FileResponse(tmp.name, media_type="text/csv", filename="site_report.csv")

@app.get("/api/reports/inventory")
async def get_inventory_report():
    materials = []
    async for material in materials_collection.find():
        materials.append(material_helper(material))
    df = pd.DataFrame(materials)
    return JSONResponse(content=df.to_dict(orient="records"))

@app.get("/api/reports/inventory/csv")
async def get_inventory_report_csv():
    materials = []
    async for material in materials_collection.find():
        materials.append(material_helper(material))
    df = pd.DataFrame(materials)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        df.to_csv(tmp.name, index=False)
        return FileResponse(tmp.name, media_type="text/csv", filename="inventory_report.csv")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)