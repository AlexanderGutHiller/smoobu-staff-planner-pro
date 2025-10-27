
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class TimeLog(Base):
    __tablename__ = "time_logs"
    id = Column(Integer, primary_key=True)
    staff_id = Column(Integer)
    task_id = Column(Integer)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
