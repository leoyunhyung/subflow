from django.contrib import admin

from .models import Settlement, SettlementHistory, SettlementRate, UserSettlement

admin.site.register(Settlement)
admin.site.register(UserSettlement)
admin.site.register(SettlementRate)
admin.site.register(SettlementHistory)
