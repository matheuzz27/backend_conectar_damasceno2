# /config/urls.py (Modificado para Auth)

from django.contrib import admin
from django.urls import path, include
# 1. Importa as views do simplejwt
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # 2. Endpoint da nossa API principal (que já tínhamos)
    path('api/', include('api.urls')),
    
    # 3. ENDPOINTS DE AUTENTICAÇÃO (NOVOS)
    # O frontend enviará o 'username' e 'password' para este link
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    # O frontend usará este link para obter um novo token (refresh) sem pedir a senha novamente
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]