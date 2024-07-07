import datetime
import time

from subarulink import Controller, SubaruException
from aiohttp import ClientSession
import asyncio
import json
import boto3


class subawoo:
    ctrl: Controller
    config: dict
    car: str
    raw_data: dict
    car_data: dict
    ddb: object

    def get_remote_config(self):
        param = boto3.client("ssm").get_parameter(Name="subawoo", WithDecryption=True)
        self.config = json.loads(param["Parameter"]["Value"])
        print("fetched remote config")

    def sync_to_ddb(self):
        self.ddb.put_item(Item={
            "vin": self.car,
            "ddbAt": int(time.time()),
            "raw_data": json.dumps(self.raw_data, default=str),
            "known_data": json.dumps(self.car_data)
        })

    def sync_from_ddb(self):
        item = self.ddb.get_item(Key={
            "vin": self.car
        })
        self.raw_data = json.loads(item["Item"]["raw_data"])
        self.car_data = json.loads(item["Item"]["known_data"])

    def init(self):
        self.car_data = {}
        self.ddb = boto3.resource("dynamodb").Table("subawoo")
        self.ctrl = Controller(
            ClientSession(),
            self.config["username"],
            self.config["password"],
            self.config["device_id"],
            self.config["pin"],
            self.config["device_name"],
            country=self.config["country"],
        )
        self.car = self.config.get("vin", "")

    async def connect(self):
        try:
            if await self.ctrl.connect():
                if not self.car:
                    self.car = self.ctrl.get_vehicles().pop()

        except SubaruException as ex:
            return False

    async def fetch(self):
        await self.ctrl.fetch(self.car, force=True)
        self.raw_data = await self.ctrl.get_data(self.car)
        self.car_data = {
            "odometer": self.mpg(self.raw_data["vehicle_status"]["ODOMETER"]),
            "gasMiles": self.mpg(self.raw_data["vehicle_status"]["DISTANCE_TO_EMPTY_FUEL"]),
            "evMiles": self.mpg(self.raw_data["vehicle_status"]["EV_DISTANCE_TO_EMPTY"]),
            "fuel": self.mpg(self.raw_data["vehicle_status"]["AVG_FUEL_CONSUMPTION"]),
            "syncAt": self.to_utc(self.raw_data["vehicle_status"]["TIMESTAMP"]),
            "fetchAt": self.to_utc(self.raw_data["last_fetch"]),
        }
        print("fetched car data")

    async def deep_fetch(self):
        await self.ctrl.update(self.car, force=True)
        print("updated car date")
        await self.fetch()

    def to_utc(self, stamp: datetime.datetime) -> int:
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=datetime.timezone.utc)
        return int(stamp.timestamp())

    def km_to_miles(self, meters: int) -> str:
        if meters is None:
            return "0"
        return "%0.1f" % (float(meters or 0) * 0.62137119)

    def mpg(self, data: float) -> str:
        if data == 0 or data is None:
            return "0"
        return "%0.1f" % round(data, 1)


# persistent state between lambda calls
LOOP = asyncio.get_event_loop()
s = subawoo()
s.get_remote_config()
s.init()
last_ddb = 0


async def goCarGo(cmd="std"):
    updated = False
    if not s.car:
        await s.connect()

    # minutely fetch from ddb
    deltaSeconds = abs(int(time.time()) - last_ddb)
    if "ddb" == cmd or deltaSeconds > 60:
        s.sync_from_ddb()
    # hourly fetch from subaru api. not more often than every 5 minutes
    deltaSeconds = abs(int(time.time()) - s.car_data.get("fetchAt", 0))
    if (deltaSeconds > 60 * 5) and ("fetch" == cmd or deltaSeconds > 60 * 60):
        await s.fetch()
        updated = True

    # 12-hourly fetch from car. not more often than every 6 hours.
    deltaSeconds = abs(int(time.time()) - s.car_data.get("syncAt", 0))
    if (deltaSeconds > 60 * 60 * 6) and ("update" == cmd or deltaSeconds > 60 * 60 * 12):
        await s.deep_fetch()
        updated = True

    if updated:
        s.sync_to_ddb()


def handler(event, context):
    cmd = event.get("queryStringParameters", {}).get("cmd", "std")
    LOOP.run_until_complete(goCarGo(cmd))
    return s.car_data
