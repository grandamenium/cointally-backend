from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views
from .views import ExchangeCredentialViewSet, CsvUploadView, CombinedTransactionView, TaxCalculationView, \
    WalletHoldingsView, PortfolioSummaryView, UserWalletAddressesView, TaxReportViewSet, CsvImportHistoryView, \
    TransactionInsightsView, PortfolioAnalyticsView

router = DefaultRouter()
router.register(r'wallets', views.WalletViewSet, basename='wallet')
router.register(r'premium', views.PremiumFeatureViewSet, basename='premium')
router.register(r'exchanges', ExchangeCredentialViewSet, basename='exchange')
router.register(r'tax-reports', TaxReportViewSet, basename='tax-reports')

urlpatterns = [
    path('', include(router.urls)),
    path('auth/register/', views.UserRegistrationView.as_view(), name='register'),
    path('auth/login/', views.UserLoginView.as_view(), name='login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/profile/', views.UserProfileView.as_view(), name='profile'),
    # Premium subscription endpoints
    path('subscriptions/create/', views.SubscriptionCreateView.as_view(), name='create_subscription'),
    path('subscriptions/webhook/', views.SubscriptionWebhookView.as_view(), name='subscription_webhook'),
    path('subscriptions/status/', views.SubscriptionStatusView.as_view(), name='subscription_status'),
    # Enhanced CSV Import endpoints
    path('csv/upload/', CsvUploadView.as_view(), name='csv-upload'),
    path('csv/imports/', CsvImportHistoryView.as_view(), name='csv-imports'),

    # Enhanced Analytics endpoints
    path('portfolio/analytics/', PortfolioAnalyticsView.as_view(), name='portfolio-analytics'),
    path('transactions/insights/', TransactionInsightsView.as_view(), name='transaction-insights'),
    path('transactions/combined/', CombinedTransactionView.as_view(), name='combined_transactions'),
    path('wallets/<str:wallet_id>/holdings/', WalletHoldingsView.as_view(), name='wallet_holdings'),
    path('portfolio/summary/', PortfolioSummaryView.as_view(), name='portfolio_summary'),

    path('taxes/calculate/', TaxCalculationView.as_view(), name='calculate_taxes'),
    path('auth/wallet-addresses/', UserWalletAddressesView.as_view(), name='wallet_addresses'),

    # Coinbase OAuth endpoints
    path('coinbase/oauth/authorize/', views.coinbase_oauth_authorize, name='coinbase_oauth_authorize'),
    path('coinbase/oauth/callback/', views.coinbase_oauth_callback, name='coinbase_oauth_callback'),
    path('coinbase/oauth/revoke/', views.coinbase_oauth_revoke, name='coinbase_oauth_revoke'),
    path('coinbase/oauth/status/', views.coinbase_oauth_status, name='coinbase_oauth_status'),

]
