from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'wallets', views.WalletViewSet, basename='wallet')
router.register(r'premium', views.PremiumFeatureViewSet, basename='premium')

urlpatterns = [
    path('', include(router.urls)),
]