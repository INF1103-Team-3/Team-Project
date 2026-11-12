"""Thin HTTP registrations: delegate input/output to the BIS web IO Manager."""
from fastapi import APIRouter, Depends, Header, Request
from BIS.classes.register_model import RegisterModel
from BIS.classes.login_model import LoginModel
from BIS.classes.verify_otp_model import VerifyOtpModel
from BIS.classes.resend_otp_model import ResendOtpModel
from BIS.classes.profile_model import ProfileModel
from BIS.classes.search_request_model import SearchRequestModel
from BIS.classes.chat_request_model import ChatRequestModel
from BIS.classes.favorite_toggle_model import FavoriteToggleModel
from BRNS.classes.route_request_model import RouteRequestModel


def get_web_io(request: Request):
    return request.app.state.runtime.io


def register_routes(app):
    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health(io=Depends(get_web_io)):
        return io.health()

    @router.get("/cuisines")
    def cuisines(io=Depends(get_web_io)):
        return io.cuisines()

    @router.get("/active-model")
    def active_model(io=Depends(get_web_io)):
        return io.active_model()

    @router.post("/auth/register")
    def register(payload: RegisterModel, io=Depends(get_web_io)):
        return io.register(payload.model_dump())

    @router.post("/auth/login")
    def login(payload: LoginModel, io=Depends(get_web_io)):
        return io.login(payload.model_dump())

    @router.post("/auth/verify-otp")
    def verify(payload: VerifyOtpModel, io=Depends(get_web_io)):
        return io.verify(payload.model_dump())

    @router.post("/auth/resend-otp")
    def resend(payload: ResendOtpModel, io=Depends(get_web_io)):
        return io.resend(payload.model_dump())

    @router.get("/auth/me")
    def me(authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.me(authorization)

    @router.post("/auth/logout")
    def logout(authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.logout(authorization)

    @router.get("/profile")
    def profile(user_id: str | None = None, authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.profile(authorization, user_id)

    @router.post("/profile")
    def save_profile(payload: ProfileModel, authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.save_profile(authorization, payload.model_dump())

    @router.post("/search")
    def search(payload: SearchRequestModel, authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.search(authorization, payload.model_dump())

    @router.post("/chat")
    def chat(payload: ChatRequestModel, authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.chat(authorization, payload.model_dump())

    @router.post("/route")
    def route(payload: RouteRequestModel, io=Depends(get_web_io)):
        return io.route(payload.model_dump())

    @router.get("/favorites")
    def favorites(authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.favorites(authorization)

    @router.post("/favorites")
    def toggle(payload: FavoriteToggleModel, authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.toggle_favorite(authorization, payload.model_dump())

    @router.delete("/favorites")
    def delete_favorite(place_key: str, authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.delete_favorite(authorization, place_key)

    @router.get("/history")
    def history(authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.history(authorization)

    @router.get("/recent-searches")
    def recent(authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.recent(authorization)

    @router.delete("/history")
    def clear_history(authorization: str | None = Header(default=None), io=Depends(get_web_io)):
        return io.clear_history(authorization)

    app.include_router(router)
