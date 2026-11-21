"""Separation-design Portal, retaining PHA ChatSession/history/logger/SSE transport."""
import asyncio
import os
import uuid
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Literal
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, model_validator
from api.utils.chat_logger import ChatSessionLogger
from sepmind.utils.request_stats import request_stats
sessions={}

@asynccontextmanager
async def lifespan(app):
    snapshot=os.environ.get('SEPMIND_RESTORE_SNAPSHOT') or os.environ.get('PHA_RESTORE_SNAPSHOT')
    if snapshot:
        restore_engineering_sessions(json.loads(Path(snapshot).read_text(encoding='utf-8')))
    yield
    from api.topology import stop_topology_jobs
    stop_topology_jobs()
    for session in sessions.values():session.logger.close()
    sessions.clear()

app=FastAPI(title="Expert-guided Separation Design",version="0.2.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:3000","http://127.0.0.1:3000"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

class SessionConfig(BaseModel):
    provider: str="deepseek"
    model_id: str="deepseek-flash"
    baseline: str="sepmind"
    persona_id: str="engineering"  # Legacy logger/session metadata; no persona data is loaded.
    user_id: str="engineering"
    workspace: Literal["engineering"]="engineering"
    engineering_basis: Optional[Dict[str,Any]]=None

    @model_validator(mode="before")
    @classmethod
    def defaults(cls,values):
        if isinstance(values,dict):
            values=dict(values)
            if values.get('baseline') == 'pha':
                values['baseline'] = 'sepmind'
            provider=values.get('provider','deepseek')
            if provider=='qwen':
                from sepmind.llm.local_credentials import qwen_settings
                default=os.environ.get('QWEN_MODEL') or qwen_settings().get('model') or 'qwen-plus'
            else:default='deterministic' if provider=='deterministic' else os.environ.get('DEEPSEEK_MODEL') or 'deepseek-flash'
            values.setdefault('model_id',default)
        return values


class ModelOption(BaseModel):
    """Available model option."""
    id: str
    name: str
    provider: str
    description: Optional[str] = None
    available: bool = True

class BaselineOption(BaseModel):
    """Available baseline option."""
    id: str
    name: str
    description: str
    architecture: str

class ChatMessage(BaseModel):
    """A chat message."""
    role: Literal['user', 'assistant']
    content: str
    timestamp: Optional[str] = None

class ChatRequest(BaseModel):
    """Request to send a message."""
    message: str

class ChatResponse(BaseModel):
    """Response from the chat endpoint."""
    message: ChatMessage
    session_id: str
    processing_time_ms: Optional[float] = None

class SessionState(BaseModel):
    """Current state of a session."""
    session_id: str
    config: SessionConfig
    message_count: int
    created_at: str
    last_activity: str
    status: str

class SessionResponse(BaseModel):
    """Response when creating a session."""
    session_id: str
    config: SessionConfig
    created_at: str
    status: str = 'ready'

class ChatSession:
    def __init__(self, session_id: str, config: SessionConfig):
            self.session_id = session_id
            self.config = config
            self.created_at = datetime.now()
            self.last_activity = datetime.now()
            self.messages: List[ChatMessage] = []
            self.agent = None
            self._initialized = False

            # Initialize structured logger
            from pathlib import Path
            logs_root = Path(__file__).parent.parent / "chat_logs"
            self.logger = ChatSessionLogger(
                user_id=config.user_id,
                session_id=session_id,
                baseline=config.baseline,
                provider=config.provider,
                model_id=config.model_id,
                persona_id=config.persona_id,
                logs_root=logs_root,
            )

    def _initialize_agent(self):
        if self._initialized:return
        from sepmind.engineering.agents.process import create_engineering_orchestrator
        if self.agent is None:
            self.agent=create_engineering_orchestrator(basis=self.config.engineering_basis)
        if self.config.provider!="deterministic":
            self.agent.configure(provider=self.config.provider,model_name=self.config.model_id)
        self._initialized=True

    async def send_message(self, user_message: str, task_updates=None) -> str:
            """Send a message and get a response."""
            import traceback

            try:
                self._initialize_agent()
            except Exception as e:
                traceback.print_exc()
                raise

            self.last_activity = datetime.now()

            # Add user message to history
            self.messages.append(ChatMessage(
                role="user",
                content=user_message,
                timestamp=datetime.now().isoformat(),
            ))

            # Begin logging this turn — capture all stdout/stderr
            capture = self.logger.begin_turn(user_message)

            # Get response from agent (run in thread pool to not block)
            start_time = datetime.now()
            try:
                with capture:
                    loop = asyncio.get_event_loop()
                    if task_updates is not None:
                        if self.config.workspace != "engineering":
                            raise ValueError("Structured engineering updates require an engineering session")
                        from functools import partial
                        response = await loop.run_in_executor(None,partial(self.agent.respond,user_message,task_updates=task_updates))
                    else:
                        response = await loop.run_in_executor(None,self.agent.respond,user_message)
                    if self.config.workspace == 'engineering':
                        self.config.engineering_basis = self.agent.basis.model_dump()
            except Exception as e:
                processing_ms = (datetime.now() - start_time).total_seconds() * 1000
                # Still log the failed turn
                self.logger.end_turn(
                    assistant_response=f"[ERROR] {e}",
                    processing_time_ms=processing_ms,
                    agents_called=list(request_stats.agents_called),
                    tools_used=dict(request_stats.tools_used),
                    errors=request_stats.errors + 1,
                )
                print("=" * 60)
                print("ERROR in agent.respond:")
                traceback.print_exc()
                print("=" * 60)
                raise

            processing_ms = (datetime.now() - start_time).total_seconds() * 1000

            # Finalize the turn log with stats from request_stats
            self.logger.end_turn(
                assistant_response=response,
                processing_time_ms=processing_ms,
                agents_called=list(request_stats.agents_called),
                tools_used=dict(request_stats.tools_used),
                errors=request_stats.errors,
            )

            # Add assistant message to history
            self.messages.append(ChatMessage(
                role="assistant",
                content=response,
                timestamp=datetime.now().isoformat(),
            ))

            return response

    def get_state(self) -> SessionState:
            """Get current session state."""
            return SessionState(
                session_id=self.session_id,
                config=self.config,
                message_count=len(self.messages),
                created_at=self.created_at.isoformat(),
                last_activity=self.last_activity.isoformat(),
                status="ready" if self._initialized else "pending",
            )

@app.get("/config")
async def get_config():
    model=os.environ.get("DEEPSEEK_MODEL") or "deepseek-flash"
    from sepmind.llm.local_credentials import qwen_settings
    qwen=os.environ.get('QWEN_MODEL') or qwen_settings().get('model') or 'qwen-plus'
    return {"providers":["deepseek","qwen","deterministic"],"models":{"deepseek":[{"id":model,"name":model,"provider":"deepseek"}],"qwen":[{"id":qwen,"name":qwen,"provider":"qwen"}],"deterministic":[{"id":"deterministic","name":"No-LLM numerical workflow","provider":"deterministic"}]},"baselines":[{"id":"sepmind","name":"SepMind expert-guided separation design","architecture":"Expert-guided orchestrator, three specialists, and independent numerical review"}],"defaults":{"provider":"deepseek","model_id":model,"workspace":"engineering"},"user_study_mode":False}

@app.post("/sessions",response_model=SessionResponse)
async def create_session(config:SessionConfig):
    if config.provider not in ("deepseek","qwen","deterministic"):
        raise HTTPException(400,"Engineering LLM provider must be DeepSeek or Qwen; deterministic is no-LLM mode")
    if config.baseline!="sepmind":
        raise HTTPException(400,"Engineering baseline adapters are not yet qualified")
    from sepmind.engineering.schemas.process import parse_process_basis
    try:parse_process_basis(config.engineering_basis or {})
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    identifier=str(uuid.uuid4())[:8]
    session=ChatSession(identifier,config)
    sessions[identifier]=session
    return SessionResponse(session_id=identifier,config=config,created_at=session.created_at.isoformat())


@app.get('/')
async def root():
    """Root endpoint with API info."""
    return {'name': 'SepMind API', 'version': '1.0.0', 'docs': '/docs', 'status': 'running'}

@app.get('/health')
async def health_check():
    """Health check endpoint."""
    return {'status': 'healthy', 'timestamp': datetime.now().isoformat()}

@app.get('/sessions/{session_id}', response_model=SessionState)
async def get_session(session_id: str):
    """Get the current state of a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail='Session not found')
    return sessions[session_id].get_state()

@app.delete('/sessions/{session_id}')
async def delete_session(session_id: str):
    """Delete a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail='Session not found')
    session = sessions[session_id]
    if hasattr(session, 'logger') and session.logger:
        session.logger.close()
    del sessions[session_id]
    return {'status': 'deleted', 'session_id': session_id}

@app.get('/sessions/{session_id}/messages', response_model=List[ChatMessage])
async def get_messages(session_id: str):
    """Get all messages in a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail='Session not found')
    return sessions[session_id].messages

@app.post('/sessions/{session_id}/chat', response_model=ChatResponse)
async def send_chat_message(session_id: str, request: ChatRequest):
    """Send a message and get a response."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail='Session not found')
    session = sessions[session_id]
    start_time = datetime.now()
    try:
        response_text = await session.send_message(request.message)
    except Exception as e:
        import traceback
        print('=' * 60)
        print('ERROR in send_chat_message:')
        traceback.print_exc()
        print('=' * 60)
        raise HTTPException(status_code=500, detail=str(e))
    processing_time = (datetime.now() - start_time).total_seconds() * 1000
    return ChatResponse(message=ChatMessage(role='assistant', content=response_text, timestamp=datetime.now().isoformat()), session_id=session_id, processing_time_ms=processing_time)

@app.post('/sessions/{session_id}/chat/stream')
async def stream_chat_message(session_id: str, request: ChatRequest):
    """Send a message and stream intermediate steps + final response via SSE.
    
    Events:
      event: step     — intermediate progress update
      event: result   — final response (terminal event)
      event: error    — error (terminal event)
    """
    import json
    import threading
    from fastapi.responses import StreamingResponse
    from sepmind.streaming import create_emitter, destroy_emitter, bind_thread, unbind_thread, emit_result, emit_error, get_queue
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail='Session not found')
    session = sessions[session_id]
    emitter_id = create_emitter()

    def run_agent():
        bind_thread(emitter_id)
        start = datetime.now()
        capture = session.logger.begin_turn(request.message)
        try:
            with capture:
                session._initialize_agent()
                session.last_activity = datetime.now()
                session.messages.append(ChatMessage(role='user', content=request.message, timestamp=datetime.now().isoformat()))
                response_text = session.agent.respond(request.message)
                session.messages.append(ChatMessage(role='assistant', content=response_text, timestamp=datetime.now().isoformat()))
            elapsed_ms = (datetime.now() - start).total_seconds() * 1000
            session.logger.end_turn(assistant_response=response_text, processing_time_ms=elapsed_ms, agents_called=list(request_stats.agents_called), tools_used=dict(request_stats.tools_used), errors=request_stats.errors)
            emit_result(response_text, elapsed_ms)
        except Exception as e:
            import traceback
            traceback.print_exc()
            elapsed_ms = (datetime.now() - start).total_seconds() * 1000
            session.logger.end_turn(assistant_response=f'[ERROR] {e}', processing_time_ms=elapsed_ms, agents_called=list(request_stats.agents_called), tools_used=dict(request_stats.tools_used), errors=request_stats.errors + 1)
            emit_error(str(e))
        finally:
            unbind_thread()
    agent_thread = threading.Thread(target=run_agent, daemon=True)
    agent_thread.start()

    async def event_stream():
        from queue import Empty
        queue = get_queue(emitter_id)
        if not queue:
            return
        try:
            while True:
                try:
                    event = queue.get_nowait()
                except Empty:
                    await asyncio.sleep(0.15)
                    continue
                event_type = event.get('type', 'step')
                yield f'event: {event_type}\ndata: {json.dumps(event)}\n\n'
                if event_type in ('result', 'error'):
                    break
        finally:
            destroy_emitter(emitter_id)
    return StreamingResponse(event_stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no'})

@app.get('/sessions')
async def list_sessions():
    """List all active sessions."""
    return {'sessions': [{'session_id': sid, 'baseline': s.config.baseline, 'persona': s.config.persona_id, 'message_count': len(s.messages), 'created_at': s.created_at.isoformat()} for sid, s in sessions.items()], 'count': len(sessions)}

def restore_engineering_sessions(snapshot):
    """Restore explicitly supplied local engineering data without making LLM calls."""
    from sepmind.engineering.agents.process import create_engineering_orchestrator
    from sepmind.engineering.schemas import DesignState
    from sepmind.engineering.schemas.process import ProcessDesignBasis, ProcessDesignState
    for item in snapshot.get('sessions',[]):
        config=SessionConfig.model_validate(item['config'])
        if config.provider not in ('deepseek','qwen','deterministic') or config.baseline!='sepmind':
            raise ValueError('Only engineering sessions can be restored')
        identifier=item['session_id']
        if identifier in sessions:continue
        session=ChatSession(identifier,config)
        session.messages=[ChatMessage.model_validate(m) for m in item.get('messages',[])]
        session.created_at=datetime.fromisoformat(item['created_at'])
        session.last_activity=datetime.fromisoformat(item['last_activity'])
        session.agent=create_engineering_orchestrator(basis=config.engineering_basis)
        schema=ProcessDesignState if isinstance(session.agent.basis,ProcessDesignBasis) else DesignState
        states=[schema.model_validate(r) for r in item.get('runs',[])]
        session.agent.runs=states
        if states:
            session.agent.state=states[-1]
            session.agent.basis=states[-1].basis.model_copy(deep=True)
            session.config.engineering_basis=session.agent.basis.model_dump()
        sessions[identifier]=session


from api.engineering import router as engineering_router
app.include_router(engineering_router)
app.include_router(engineering_router,prefix="/api",include_in_schema=False)
from api.topology import router as topology_router
app.include_router(topology_router)
app.include_router(topology_router,prefix="/api",include_in_schema=False)
from api.shortcut_routes import router as shortcut_router
app.include_router(shortcut_router)
