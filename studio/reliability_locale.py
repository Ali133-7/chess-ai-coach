"""Human-facing messages for the new account and analysis workflows."""
from fastapi import HTTPException
from .locale import language

AR={
 'Game not found':'المباراة غير موجودة ضمن حسابك.',
 'Completed analysed games only':'هذه الميزة للمباريات المكتملة والمحللة فقط.',
 'Position not found':'الوضعية غير موجودة.',
 'Two searches may be outstanding per account':'لديك بحثان قيد التنفيذ. انتظر اكتمال أحدهما.',
 'Search queue full':'طابور البحث ممتلئ حالياً. حاول لاحقاً.',
 'Search not found':'البحث غير موجود ضمن حسابك.',
 'Linked username does not identify a side in this game':'الاسم المرتبط بحسابك لا يطابق أحد طرفي هذه المباراة.',
 'Unknown skill':'هذه المهارة غير معروفة.',
 'Sign in again with your second factor':'سجّل الدخول مجدداً باستخدام رمز التحقق بخطوتين.',
 'Current password required':'كلمة المرور الحالية غير صحيحة.',
 'A fresh authentication code or recovery code is required':'أدخل رمزاً جديداً من تطبيق المصادقة أو أحد رموز الاسترداد غير المستخدمة.',
 'Invalid or expired link':'الرابط غير صالح أو انتهت صلاحيته. اطلب رابطاً جديداً.',
 'MFA is already enabled':'التحقق بخطوتين مفعّل بالفعل.',
 'MFA is not enabled':'التحقق بخطوتين غير مفعّل.',
 'Enrollment expired':'انتهت مهلة الإعداد. ابدأ إعداد التحقق بخطوتين مجدداً.',
 'Invalid code':'الرمز غير صحيح. تحقق من ساعة الجهاز والرمز الحالي.',
 'Invalid or expired authentication challenge':'الرمز غير صحيح أو انتهت مهلة الدخول. حاول تسجيل الدخول مجدداً.',
 'Session not found':'الجلسة غير موجودة ضمن حسابك.',
 'Enable two-factor authentication in account settings before administration':'فعّل التحقق بخطوتين من إعدادات حسابك قبل استخدام الإدارة.',
}
class LocalizedError(HTTPException):
 def __init__(self,status_code,detail,headers=None):super().__init__(status_code,AR.get(detail,detail) if language()=='ar' else detail,headers)
