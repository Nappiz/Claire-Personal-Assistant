from neo4j import GraphDatabase
import logging
from configs.settings import settings

logger = logging.getLogger(__name__)

class Neo4jConnection:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        if self.driver:
            self.driver.close()

    def verify_connectivity(self):
        try:
            self.driver.verify_connectivity()
            logger.info("Successfully connected to Neo4j.")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            return False

    def query(self, query, parameters=None, db=None):
        assert self.driver is not None, "Driver not initialized!"
        session = None
        response = None
        try: 
            session = self.driver.session(database=db) if db else self.driver.session() 
            response = list(session.run(query, parameters))
        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise e
        finally: 
            if session:
                session.close()
        return response

neo4j_db = Neo4jConnection(settings.NEO4J_URI, settings.NEO4J_USER, settings.NEO4J_PASSWORD)
