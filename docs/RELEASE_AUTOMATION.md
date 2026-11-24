# النشر التجريبي والترقية والاستعادة

الملفات هنا أدوات تشغيل قابلة للمراجعة وليست تفويضاً تلقائياً لتغيير سيرفر قائم. لا تنفذ workflows الجديدة نشر إنتاج بمجرد push. لا تُحفظ بيانات البريد أو SSH أو قواعد المستخدمين أو مفاتيح التشفير في المستودع.

## صورة الإصدار

workflow `Publish immutable release` يعمل يدوياً، ويشترط نجاح workflow `Tests` **لنفس SHA** قبل البناء والنشر إلى GHCR. يبني Dockerfile الكامل ويمرر `APP_REVISION`، ويحفظ SHA في OCI label وفي `STUDIO_RELEASE_SHA`، ويطبع مرجع `repository@sha256:...` في ملخص GitHub. لا تعتمد production على tag متحرك مثل latest.

اختبارات `Tests` تشمل بناء الصورة الحقيقية وتشغيلها بلا شبكة، ثم اختبار ترحيل على قواعد منسوخة، إضافة إلى اختبارات Python والمتصفح وDOM والأمان وتجربة حمل قصيرة. البيانات العامة تستخرج وتتحقق ببصمتها عند البناء؛ لا تُدمج قاعدة تشغيل.

## بيئة تجريبية مستمرة

`deploy/compose.staging.yaml` يستخدم project وvolume منفصلين، ومنفذ loopback 18002، وشبكة داخلية تمنع الخروج إلى المزودين. لا تنسخ مفاتيح التشغيل إليه. بوابات الدفع غير مفعلة افتراضياً ولا تعمل مزامنة Chess.com أو عامل SMTP فيه.

```bash
export CHESS_RELEASE_IMAGE='ghcr.io/ali133-7/chess-ai-coach@sha256:ACTUAL_64_HEX_DIGEST'
docker compose -f deploy/compose.staging.yaml up -d
```

استبدل القيمة بالبصمة الفعلية من workflow؛ المثال ليس قيمة صالحة. للوصول من جهازك عبر اتصال مشفر:

```bash
ssh -C -N -L 18002:127.0.0.1:18002 deploy@YOUR_SERVER
```

افتح `http://127.0.0.1:18002` وأنشئ حساباً تجريبياً. لا تربط volume الإنتاج أو `.env` الخاص به بهذه البيئة. الترحيل الآلي الآتي يضيف أيضاً تجربة قصيرة على **نسخة قواعد حقيقية** بلا شبكة، دون إتاحة تلك النسخة على منفذ ويب.

## تهيئة أدوات المشغّل مرة واحدة

ضع نسخة مراجعة ومثبتة من `scripts/encrypted_backup.py` و`promote_release.py` و`deploy/ssh_entry.py` و`deploy/root_release.py` تحت `/opt/chess-ops`، بملكية root ومن دون صلاحية كتابة لحساب SSH. أنشئ venv للمشغّل وثبّت متطلبات الإصدار المقفلة؛ سكريبت التشفير يستخدم cryptography، وCLI يحتاج Docker Compose V2 وSSH/SCP وPython على Linux.

انسخ `deploy/release.example.json` و`backup.example.json` إلى `/etc/chess-private` بصلاحيات 700 للمجلد و600 للملفات. راجع أسماء volume وCompose والخدمات والمؤقتات على الخادم؛ لا تفترض تطابقها. أدخل كل كاتب نشط: `studio` و`studio-worker` و`studio-sync`، وأيضاً control-sync/mail-worker/daily-exercises إن كانت تعمل عبر Compose. المثال يعكس نمط السيرفر ذي مؤقتي systemd؛ إذا اختلفت وحداته صححها قبل التنفيذ.

أنشئ مفتاحاً عشوائياً **مرة واحدة**:

```bash
sudo /opt/chess-ops/venv/bin/python /opt/chess-ops/scripts/encrypted_backup.py keygen --key-file /etc/chess-private/backup-key
```

الأمر يرفض استبدال مفتاح موجود ولا يطبع محتواه. احفظ نسخة آمنة منفصلة عنه خارج السيرفر؛ لا يمكن فك النسخ عند فقدانه. يبقى المفتاح خارج data volume وخارج حمولة الأرشيف المشفر.

## النسخ المشفر واختبار الاستعادة

```bash
sudo /opt/chess-ops/venv/bin/python /opt/chess-ops/scripts/encrypted_backup.py run --config /etc/chess-private/backup.json
```

الخطوات: SQLite Online Backup لكل قاعدة، وفحص integrity، وجمع الملفات الخاصة، وmanifest للأحجام وSHA-256، ثم tar.gz وتشفير تدفقي AES-256-GCM بنونس عشوائي وتوثيق header. بعدها يفك الأرشيف إلى مكان مؤقت ويتحقق من التوثيق والمسارات والبصمات وintegrity وFK قبل إعلان نجاح تجربة الاستعادة. كل قاعدة متسقة بذاتها؛ لتناسق حالة التطبيق بين عدة قواعد أوقف كتّابها، كما يفعل مسار الترقية.

`data_directory` يجمع ملفات ومجلدات volume الخاصة، بما فيها مفاتيح المعلّم القديمة وcontrol-private وأسرار TOTP، دون قواعد SQLite الحية وWAL/SHM والسجلات ومجلدات backups/private-backups. `private_includes` يضيف `.env` وCompose وأي ملف خاص خارج volume، مثل اعتماد SMTP إن وضعته في مكان آخر. راجع manifest لتتأكد من تغطية ملفاتك الفعلية. قاعدة telemetry اختيارية؛ أضفها إلى `databases` إن أردت استعادتها أيضاً.

النقل الخارجي اختياري في الإعداد ويُفعّل بإدخال `ssh_destination` بصيغة `backup@backup-host:/absolute/directory` و`identity_file` عند الحاجة. يلزم إنشاء المجلد البعيد وتهيئة مفتاح SSH وknown_hosts موثوق مسبقاً. لا تُقبل shell expressions ولا يُعطّل فحص هوية المضيف. يرفع الملف إلى `.part`، ويتحقق من SHA-256، ثم يعيد تسميته ويتحقق من الملف النهائي. النقل الفاشل لا يُوصف بأنه نسخة خارجية ناجحة. `null` يعني نسخة محلية فقط.

```bash
sudo /opt/chess-ops/venv/bin/python /opt/chess-ops/scripts/encrypted_backup.py restore --file /path/to/backup.enc --key-file /etc/chess-private/backup-key
```

الأمر السابق تجربة تحقق فقط. أضف `--destination /new/empty-destination` لاستخراج نسخة موثقة؛ يجب أن يكون المسار غير موجود. لا يستبدل السكريبت قاعدة حية. ملفات الاستعادة تحت databases وprivate، وmanifest يبين مساراتها الأصلية للمراجعة؛ لا يستخدمها للكتابة خارج الوجهة. قبل استعادة تشغيل فعلية أوقف الكتّاب، وراجع أثر فقد البيانات الأحدث، واربط الملفات والمفاتيح الصحيحة، ثم اختبر التشغيل.

تتوفر وحدتا `deploy/systemd/chess-encrypted-backup.service` و`.timer` للتشغيل يومياً 03:15 بتوقيت بغداد، مع تأخير عشوائي خمس دقائق وPersistent. لا تُثبتان تلقائياً. لا توجد سياسة حذف تلقائي للنسخ القديمة؛ حدد الاحتفاظ بناءً على مساحة التخزين والمتطلبات التشغيلية.

## الترقية المثبتة بالبصمة

```bash
sudo /opt/chess-ops/venv/bin/python /opt/chess-ops/scripts/promote_release.py --config /etc/chess-private/release.json --image GHCR_REPOSITORY_AT_SHA256 --commit FULL_40_HEX_COMMIT
```

بدون `--execute` يعرض خطة ولا يغيّر التشغيل. `--stage-only` يسحب الصورة ويختبر نسخة قواعد معزولة، ولا يغير الخدمات العاملة. الإعداد الحقيقي يجب أن يطابق repository المسموح، والصورة يجب أن تحمل SHA المصدر المطلوب.

التنفيذ بـ`--execute`:

1. قفل يمنع ترقية متزامنة، ومراجعة Compose وصورة المصدر والكتّاب والمؤقتات.
2. snapshot لقاعدتي التشغيل في مجلد محمي، وترحيل داخل حاوية بلا شبكة، والتحقق أن السجلات القائمة لم تتغير.
3. إيقاف المؤقتات والكتّاب المحددين، ثم نسخة متسقة ومشفرة وفحص استعادة محلي. لا تبدأ الترقية دون مفتاح احتياطي صالح.
4. إبطال leases القديمة بعد إيقاف العامل، دون حذف checkpoints أو نتائج الكاش.
5. تبديل صور الخدمات المشتركة ومؤقتات systemd معاً، باستخدام `--no-build`، ثم فحص الصحة والصور وحالة العمليات وعدد إعادة التشغيل.
6. إعادة المؤقتات إلى حالتها السابقة. رفع النسخة خارج السيرفر بعد استعادة الخدمة، لكي لا يطيل تعطل المضيف البعيد نافذة التوقف. فشل هذا الرفع يسجل `upload_failed_retry_required` ويحتاج إعادة محاولة؛ لا يتراجع عن كود سليم.

التراجع التلقائي عند الفشل يعيد الكود والإعدادات السابقة دون استعادة قاعدة قديمة فوق بيانات أحدث. توجد حماية خاصة: صورة قديمة بلا دعم MFA لا يجوز أن تصبح واجهة لحسابات فعّلته أو لسياسة تلزمه. عند هذا التعارض **تُوقف الواجهة ويُطلب إصدار متوافق**، بدلاً من تجاوز العامل الثاني. لا تحذف بيانات MFA لإجبار التراجع.

التراجع اليدوي يستخدم ملف الحالة الخاص للإصدار:

```bash
sudo /opt/chess-ops/venv/bin/python /opt/chess-ops/scripts/promote_release.py --rollback /var/lib/chess-releases/RELEASE/rollback-state.json --execute
```

لا يشغّل هذا الأمر لمجرد وجود ملف؛ يفحص تطابق الإصدار الحالي وتوافق MFA. احتفظ بالصورة السابقة وملفات الحالة حتى انتهاء فترة المراقبة.

## GitHub إلى الخادم

workflow `Promote verified release` يدوي، وافتراضيه staging؛ يشترط نجاح `Tests` للـSHA المحدد وأن يكون SHA هو نسخة workflow نفسها. production يستخدم بيئة GitHub منفصلة. ميزات Environments في المستودعات الخاصة تعتمد على خطة GitHub؛ إذا لم تتوفر استخدم CLI المراجَع، ولا تغيّر خصوصية المستودع لأجلها.

الأسرار المطلوبة لكل بيئة: `RELEASE_SSH_HOST` و`RELEASE_SSH_USER` و`RELEASE_SSH_KEY` و`RELEASE_KNOWN_HOSTS`. لا يستخدم workflow كلمة مرور sudo أو يطبع المفاتيح، ويتحقق من المدخلات قبل SSH ويزيل ملف المفتاح المؤقت.

ثبّت `deploy/root_release.py` باسم `/opt/chess-ops/root_release.py`، واجعل أدوات النشر بملكية root وقابلة للتنفيذ. خصص مفتاح SSH للنشر مع `restrict,command="/opt/chess-ops/deploy/ssh_entry.py"` في authorized_keys. الملف يقبل فقط `stage IMAGE COMMIT` و`promote IMAGE COMMIT`، ويثبت repository المسموح ثم يمرر arguments منفصلة بلا shell. جهّز للمستخدم إذن sudo للّانشر دون arguments فقط. مثال يراجعه المسؤول بـvisudo: `chess-release ALL=(root) NOPASSWD: /opt/chess-ops/root_release.py ""`. يستقبل اللانشر JSON محدوداً، ويرفض تغيير مسار الإعداد أو السكريبت، ويشغل Python بوضع isolated. لا تمنح المستخدم sudo عاماً بلا كلمة مرور، ولا إذن كتابة أدوات النشر أو إعداداتها أو venv. إذا لم تجهز هذه الصلاحية يرفض workflow العمل بوضوح، وتظل الترقية اليدوية متاحة.

الحالة الافتراضية للمستودع: الكود والقوالب والاختبارات جاهزة؛ لا مفاتيح SMTP أو خادم نسخ احتياطي أو صلاحية SSH للنشر مرفقة، ولم تُنشَر نسخة تشغيل تلقائياً بسبب إضافة workflow.
