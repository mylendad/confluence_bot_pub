from services.rag.handlers import (
    AttributeCompositionHandler,
    AttributeLogicHandler,
    AttributeUsageHandler,
    DatamartFactHandler,
    DatamartListHandler,
    LastYearChangesHandler,
    OwnerLookupHandler,
    ReleaseChangesHandler,
    SourceLineageHandler,
    VectorAnswerHandler,
)
from services.rag.query_parser import QueryParser


class IntentDispatcher:
    def __init__(self, metadata_repo, vector_store, history_repo, answer_generator, intent_classifier):
        self.intent_classifier = intent_classifier
        self.query_parser = QueryParser(metadata_repo)
        
        args = (metadata_repo, vector_store, history_repo, answer_generator, self.query_parser)
        
        self.handlers = {
            "datamart_list": DatamartListHandler(*args),
            "datamart_fact": DatamartFactHandler(*args),
            "release_changes": ReleaseChangesHandler(*args),
            "owner_lookup": OwnerLookupHandler(*args),
            "attribute_usage": AttributeUsageHandler(*args),
            "attribute_composition": AttributeCompositionHandler(*args),
            "last_year_changes": LastYearChangesHandler(*args),
            "transformation_logic": AttributeLogicHandler(*args),
            "source_lineage": SourceLineageHandler(*args),
        }
        self.vector_handler = VectorAnswerHandler(*args)

    def dispatch(self, question: str):
        intent = self.intent_classifier.classify(question)
        handler = self.handlers.get(intent)
        
        res = None
        if handler:
            res = handler.handle(question)
            
        if not res:
            res = self.vector_handler.handle(question)
            
        return res
