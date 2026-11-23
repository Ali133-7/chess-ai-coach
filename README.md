# Chess AI Coach / Chess Studio

منصة شطرنج بالعربية والإنكليزية: اللعب والتعلّم، مراجعة المباريات، مركز معرفة محلي ومسار تعليمي تفاعلي. هذا المستودع يجمع الكود الكامل المطابق لنسخة الواجهة المنشورة، وملفات تشغيل مستقلة؛ لا يحتوي بيانات حسابات الموقع أو مفاتيحه.

## المزايا

- Stockfish للعب والتحليل وقانونية النقلات، مع معلّم يدعم **Groq Cloud** و**xAI Grok** وOpenRouter وOpenAI كمزودين منفصلين، واختيار المزود والبدائل.
- 3865 سجل افتتاحيات، وفخاخ مع تحديد اللون، و5000 لغز مرجعي، و1500 مباراة فعلية بين أساتذة كبار مع البيانات والمصادر.
- 48 درساً ضمن 8 مراحل، وتطبيق مباشر على الرقعة، واختبار بداية ومراجعات مجدولة.
- تمارين يومية بهدف 24 وضعية مميزة مع تحقق Stockfish وشرح AI؛ حفظ سجل المستخدم لمنع التكرار التلقائي. اكتمال الدفعة يعتمد على المحرك وحصة المزود.
- تشغيل تلقائي للنقلات ونوافذ دراسة وتحليل، ودعم الهاتف والتابلت والكمبيوتر وRTL/LTR.

## تشغيل جديد باستخدام Docker

```bash
git clone https://github.com/Ali133-7/chess-ai-coach.git
cd chess-ai-coach
cp .env.example .env
docker compose build
docker compose run --rm studio python scripts/bootstrap_knowledge.py
docker compose up -d
```

افتح <http://127.0.0.1:8001> وأنشئ حساباً جديداً. التهيئة تستورد البيانات العامة فقط، وهي قابلة لإعادة التنفيذ. ليست قاعدة المستخدمين المنشورة جزءاً من Git.

لخادم بعيد أبقِ المنفذ محلياً واستخدم نفق SSH، مثلاً:

```bash
ssh -L 18001:127.0.0.1:8001 your-user@your-server
```

ثم افتح <http://127.0.0.1:18001>. ملفات compose في المستودع مخصصة لتشغيل مستقل جديد. توثيق النسخة المنشورة وترقياتها في [docs/OPERATIONS.md](docs/OPERATIONS.md).

## إعداد معلّم Groq Cloud

```bash
docker compose exec studio python configure_teacher_providers.py \
  --primary groq --model groq=openai/gpt-oss-120b
```

يطلب المفتاح بإدخال مخفي ويحفظه داخل وحدة التخزين بصلاحيات خاصة. لا تضع المفتاح في سطر الأوامر أو Git. أسماء النماذج التي يقبلها حساب المزود قد تتغير؛ اختر نموذجاً متاحاً عند الإعداد.

مثال مزود أساسي وبديل، مع أسماء نماذج حسابك:

```bash
docker compose exec studio python configure_teacher_providers.py \
  --primary groq --fallback xai \
  --model groq=YOUR_GROQ_MODEL --model xai=YOUR_XAI_MODEL
```

Groq Cloud ليس xAI Grok. يدعم الأمر أيضاً `openrouter` و`openai`.

لتفعيل التوليد الدوري على تشغيل جديد:

```bash
docker compose --profile automation up -d daily-exercises
docker compose logs --tail 50 daily-exercises
```

يعمل الفحص عند بدء الحاوية، ثم الساعة 03:15 بتوقيت بغداد مع استكمال كل ساعتين. شغّل مجدولاً واحداً فقط؛ الخادم الحالي يستخدم مؤقت systemd موجوداً بالفعل. يوضح العداد العدد الحقيقي المنشور، ولا تُنشأ نتائج بديلة وهمية عند فشل المزود.

## الاختبارات

```bash
docker compose run --rm --no-deps \
  -e STUDIO_DB=/tmp/tests/studio.sqlite3 \
  -e CHESS_KNOWLEDGE_DB=/tmp/tests/knowledge.sqlite3 \
  -e DATABASE_PATH=/tmp/tests/legacy.sqlite3 \
  studio python -m unittest discover -s tests -p 'test_*.py' -q
npm ci
npm test
```

GitHub Actions يشغّل اختبارات Python والواجهة دون مفاتيح أو طلبات مدفوعة. لا تستخدم قاعدة الإنتاج للاختبارات. توجد اختبارات إضافية داخل `studio/tests`.

## البيانات والحقوق

بيانات المعرفة وملفاتها المرجعية في `studio/knowledge/data`، مع البصمات والمصادر والتراخيص. ملف مباريات الأساتذة العام مضغوط بحجم مناسب لـGit ويُفك مع التحقق من SHA-256 أثناء البناء. تشمل الأمثلة 24 تمريناً مولداً بتاريخ 2026-11-22؛ هذه أمثلة تاريخية وليست دفعة كل يوم.

راجع [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). الاستضافة العامة تتطلب تجهيز HTTPS وإعدادات ملفات الارتباط والأصل؛ المنافذ الافتراضية مرتبطة بـlocalhost.
