import json

from django.db import migrations


CONTACT_ROWS = json.loads(
    r'''[
  {
    "excel_row": 2,
    "platform": "遠時",
    "contact_person": "(PM)陳虹毓 Tifa",
    "phone": "(02)7712-3838",
    "extension": "513062",
    "mobile": "",
    "email": "",
    "note": "傳真   /  02-7712-3835"
  },
  {
    "excel_row": 3,
    "platform": "遠時",
    "contact_person": "(發票)洪聿玟",
    "phone": "(02)7712-3838",
    "extension": "13799",
    "mobile": "",
    "email": "om-paymentservice@friday.tw",
    "note": ""
  },
  {
    "excel_row": 4,
    "platform": "遠時",
    "contact_person": "(前廠商結帳)張明珠",
    "phone": "(02)7712-3838",
    "extension": "13113",
    "mobile": "",
    "email": "sallychang@friday.tw",
    "note": ""
  },
  {
    "excel_row": 5,
    "platform": "遠時",
    "contact_person": "(廠商結帳)蕭月茵",
    "phone": "(02)7712-3838",
    "extension": "13723",
    "mobile": "",
    "email": "tiffany_hsiao@friday.tw",
    "note": "ys.hsiao@udnshopping.com"
  },
  {
    "excel_row": 6,
    "platform": "遠時",
    "contact_person": "系統(吳小姐)",
    "phone": "(02)7712-3838",
    "extension": "633",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 7,
    "platform": "遠時",
    "contact_person": "供應商客服",
    "phone": "(02)7738-8055",
    "extension": "4",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 8,
    "platform": "Friday",
    "contact_person": "(購中PM)江峯柏",
    "phone": "(02)7712-3838",
    "extension": "513078",
    "mobile": "0936-054981",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 9,
    "platform": "Friday",
    "contact_person": "金流暨帳務部 袁韻翔",
    "phone": "(02)7712-3838",
    "extension": "13799",
    "mobile": "",
    "email": "teresa_yuan@friday.tw",
    "note": ""
  },
  {
    "excel_row": 10,
    "platform": "Friday",
    "contact_person": "發票 徐小姐",
    "phone": "",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 11,
    "platform": "Friday",
    "contact_person": "(採購) 李思瑩",
    "phone": "(02)7712-3838",
    "extension": "13871",
    "mobile": "0982-182601",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 14,
    "platform": "Friday加購",
    "contact_person": "陳宥暄",
    "phone": "(02)7712-3838",
    "extension": "13116",
    "mobile": "0931121312",
    "email": "kaechen@friday.tw",
    "note": ""
  },
  {
    "excel_row": 15,
    "platform": "UDN聯合報",
    "contact_person": "客人客服",
    "phone": "(02)7737-8282",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 16,
    "platform": "UDN聯合報",
    "contact_person": "廠商客服",
    "phone": "(02)7710-7900",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 17,
    "platform": "UDN聯合報",
    "contact_person": "(PM)呂官達",
    "phone": "(02)8692-5588",
    "extension": "6016",
    "mobile": "",
    "email": "bill.lu@udnshopping.com",
    "note": ""
  },
  {
    "excel_row": 18,
    "platform": "UDN聯合報",
    "contact_person": "(精品配件 PM) 洪小姐",
    "phone": "(02)8692-5588",
    "extension": "6017",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 19,
    "platform": "UDN聯合報",
    "contact_person": "(發票) 劉盈孜小姐",
    "phone": "(02)8692-5588",
    "extension": "5992",
    "mobile": "",
    "email": "ashely.liu@udnshopping.com",
    "note": ""
  },
  {
    "excel_row": 20,
    "platform": "UDN聯合報",
    "contact_person": "(權限)王小姐",
    "phone": "(02)8692-5588",
    "extension": "5938",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 21,
    "platform": "神坊",
    "contact_person": "(PM) 劉尚軒 Bob Liu",
    "phone": "(02)7752-0688",
    "extension": "1861",
    "mobile": "0937-519282",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 22,
    "platform": "神坊",
    "contact_person": "(PM) Myan 史皓升",
    "phone": "(02)7752-0688",
    "extension": "1804",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 24,
    "platform": "神坊",
    "contact_person": "(帳務相關問題 發票)洪榛均",
    "phone": "(02)7752-0688",
    "extension": "1216",
    "mobile": "",
    "email": "tracy_hung@symphox.net",
    "note": "傳郵件申請發票"
  },
  {
    "excel_row": 25,
    "platform": "神坊",
    "contact_person": "(供應商合約) 張容菱",
    "phone": "(02)7752-0688",
    "extension": "1233",
    "mobile": "",
    "email": "irene_chang@symphox.net",
    "note": ""
  },
  {
    "excel_row": 26,
    "platform": "神坊",
    "contact_person": "(廠商客服/訂單配送/退、換貨問題、罰款/\n運費減免申請/帳號解鎖)",
    "phone": "(02)7755-3611",
    "extension": "語音選５",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 27,
    "platform": "神坊",
    "contact_person": "(廠商客服/訂單配送/退、換貨問題、罰款/\n運費減免申請/帳號解鎖) 許小姐",
    "phone": "(02)2737-5586",
    "extension": "1714",
    "mobile": "",
    "email": "supplychain@symphox.net",
    "note": ""
  },
  {
    "excel_row": 35,
    "platform": "東森",
    "contact_person": "(PM)潘翔薽",
    "phone": "(02)2943-7888",
    "extension": "3498",
    "mobile": "0933-270991",
    "email": "ariel.pan@ehsn.com.tw",
    "note": ""
  },
  {
    "excel_row": 36,
    "platform": "東森",
    "contact_person": "商品行政 陳小姐",
    "phone": "(02)2943-7888",
    "extension": "3155",
    "mobile": "",
    "email": "rae.hsieh@ehsn.com.tw",
    "note": ""
  },
  {
    "excel_row": 37,
    "platform": "東森",
    "contact_person": "(發票代開)呂慧玲",
    "phone": "(02)2943-7888",
    "extension": "2167",
    "mobile": "",
    "email": "aura.lu@sensengo.com.tw",
    "note": ""
  },
  {
    "excel_row": 38,
    "platform": "東森",
    "contact_person": "(退訂)林小姐",
    "phone": "(02)2943-7888",
    "extension": "3438",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 39,
    "platform": "博客來",
    "contact_person": "(PM/發票) 百貨二Team   Juice劉宏文",
    "phone": "(02)2782-1100",
    "extension": "233",
    "mobile": "0936215188",
    "email": "juice_liu@books.com.tw",
    "note": ""
  },
  {
    "excel_row": 43,
    "platform": "博客來",
    "contact_person": "(主管)林先生",
    "phone": "(02)2782-1100",
    "extension": "528",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 45,
    "platform": "博客來",
    "contact_person": "(對帳)林小姐",
    "phone": "(02)2782-1100",
    "extension": "318",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 46,
    "platform": "博客來",
    "contact_person": "(上下架/後台帳密管理)洪先生",
    "phone": "(02)2782-1100",
    "extension": "847",
    "mobile": "",
    "email": "req_proce_m@books.com.tw",
    "note": ""
  },
  {
    "excel_row": 47,
    "platform": "大買家",
    "contact_person": "(PM)億川",
    "phone": "(04)2310-6677",
    "extension": "2818",
    "mobile": "",
    "email": "kscafe116@savesafe.com.tw",
    "note": ""
  },
  {
    "excel_row": 48,
    "platform": "大買家",
    "contact_person": "(發票)張小姐",
    "phone": "(04)2310-6677",
    "extension": "2764",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 49,
    "platform": "大買家",
    "contact_person": "(財務)廖小姐",
    "phone": "(04)2310-6677",
    "extension": "2835",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 50,
    "platform": "亞柏",
    "contact_person": "(休閒館 PM)蕭秀丹",
    "phone": "(02)2627-3900",
    "extension": "73",
    "mobile": "",
    "email": "summer@mail.apli.com.tw",
    "note": ""
  },
  {
    "excel_row": 51,
    "platform": "亞柏",
    "contact_person": "主管 楊先生",
    "phone": "(02)2627-3900",
    "extension": "40",
    "mobile": "0985237000",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 52,
    "platform": "亞柏",
    "contact_person": "(會計)時佳祺",
    "phone": "07-813-7728",
    "extension": "",
    "mobile": "",
    "email": "kiki08012@mail.apli.com.tw",
    "note": ""
  },
  {
    "excel_row": 53,
    "platform": "亞柏",
    "contact_person": "傳真",
    "phone": "(02)2627-3899",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 55,
    "platform": "百利市",
    "contact_person": "(PM) 葉自偉",
    "phone": "(03)397-5151",
    "extension": "1073",
    "mobile": "",
    "email": "owenye@sampo.com.tw",
    "note": ""
  },
  {
    "excel_row": 57,
    "platform": "百利市",
    "contact_person": "(PM助理) 思涵",
    "phone": "(03)397-5151",
    "extension": "1074",
    "mobile": "",
    "email": "sylvie0721@sampo.com.tw",
    "note": ""
  },
  {
    "excel_row": 58,
    "platform": "百利市",
    "contact_person": "(會計)林昕宜",
    "phone": "(03)397-5151",
    "extension": "3253",
    "mobile": "",
    "email": "s062068@sampo.com.tw",
    "note": ""
  },
  {
    "excel_row": 59,
    "platform": "百利市",
    "contact_person": "(帳款)李玉婷",
    "phone": "(03)397-5151",
    "extension": "3265",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 60,
    "platform": "百利市",
    "contact_person": "(課長)余志鴻",
    "phone": "(03)397-5151",
    "extension": "3250",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 61,
    "platform": "百利市",
    "contact_person": "客服 唯倪",
    "phone": "(03)397-5151",
    "extension": "3257",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 66,
    "platform": "Myfone",
    "contact_person": "(PM部門主管) 高先生",
    "phone": "(02)6638-6888",
    "extension": "16623",
    "mobile": "0972-197-982",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 67,
    "platform": "Myfone",
    "contact_person": "(PM/發票) 張詒禎 julia chang",
    "phone": "(02)6638-6888",
    "extension": "16749",
    "mobile": "",
    "email": "juliayjchang@taiwanmobile.com",
    "note": ""
  },
  {
    "excel_row": 70,
    "platform": "Myfone",
    "contact_person": "(帳務) 林家瑜",
    "phone": "(02)6638-6888",
    "extension": "18627",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 71,
    "platform": "PC",
    "contact_person": "(招商 商品開發經理) Roy 張凱評",
    "phone": "(02)2700-0898",
    "extension": "2906",
    "mobile": "0913-279862",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 72,
    "platform": "PC",
    "contact_person": "(主管) Grace",
    "phone": "(02)2700-0898",
    "extension": "8363",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 73,
    "platform": "PC",
    "contact_person": "(PM 產品經理) 袁瑟君",
    "phone": "(02)2700-0898",
    "extension": "8255",
    "mobile": "",
    "email": "x2fox@pchome.tw",
    "note": ""
  },
  {
    "excel_row": 74,
    "platform": "PC",
    "contact_person": "(產品企劃) 強雅鈴 Amanda",
    "phone": "(02)2700-0898",
    "extension": "8461",
    "mobile": "",
    "email": "amanda990@pchome.tw",
    "note": ""
  },
  {
    "excel_row": 79,
    "platform": "PC",
    "contact_person": "(助理) Alin",
    "phone": "(02)2700-0898",
    "extension": "2602",
    "mobile": "",
    "email": "alin@staff.pchome.com.tw",
    "note": ""
  },
  {
    "excel_row": 80,
    "platform": "PC",
    "contact_person": "帳務相關 劉美娟",
    "phone": "(02)2700-0898",
    "extension": "2486",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 81,
    "platform": "PC",
    "contact_person": "客服(聯繫不到客人)吳先生",
    "phone": "(02)2700-0898",
    "extension": "8021",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 82,
    "platform": "PC",
    "contact_person": "客服電話是",
    "phone": "(02)2704-0999",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 83,
    "platform": "Pchome商店街",
    "contact_person": "(PM) 雪菱",
    "phone": "(02)2700-5658",
    "extension": "2882",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 84,
    "platform": "Pchome商店街",
    "contact_person": "(PM) 黃仁怡",
    "phone": "(02)2700-5658",
    "extension": "2922",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 86,
    "platform": "Pchome商店街",
    "contact_person": "(招商) 姜倩雯 副理",
    "phone": "(02)2700-5658",
    "extension": "5321",
    "mobile": "0932-183403",
    "email": "jill690315@gmail.com / jillchiang@pcstore.com.tw",
    "note": ""
  },
  {
    "excel_row": 87,
    "platform": "Pchome商店街",
    "contact_person": "(招商) 周小姐",
    "phone": "(02)2700-5658",
    "extension": "5316",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 88,
    "platform": "Pchome商店街",
    "contact_person": "(招商) 周小姐",
    "phone": "(02)2700-5658",
    "extension": "5371",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 89,
    "platform": "Pchome商店街",
    "contact_person": "(招商) 羅文利",
    "phone": "(02)2700-5658",
    "extension": "5361",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 90,
    "platform": "Pchome商店街",
    "contact_person": "金流/商家客服",
    "phone": "(02)2700-5658",
    "extension": "1968",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 91,
    "platform": "Pchome商店街",
    "contact_person": "系統/商家客服",
    "phone": "(02)2700-5658",
    "extension": "1966",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 92,
    "platform": "Pchome商店街",
    "contact_person": "顧客客服",
    "phone": "(02)2700-5658",
    "extension": "1977",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 93,
    "platform": "Pchome商店街",
    "contact_person": "(發票)",
    "phone": "(02)2700-5658",
    "extension": "1966",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 94,
    "platform": "Pchome商店街",
    "contact_person": "(帳務)",
    "phone": "(02)2700-5658",
    "extension": "1968",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 99,
    "platform": "Yahoo",
    "contact_person": "(招商, 權責範圍:廠商簽約) 許雅妮",
    "phone": "(02)2360-1791",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 100,
    "platform": "Yahoo",
    "contact_person": "(權責範圍:家電主管) 解崴翔 Will",
    "phone": "(02)2360-3138",
    "extension": "",
    "mobile": "0921-459592",
    "email": "willshie@oath.com",
    "note": ""
  },
  {
    "excel_row": 101,
    "platform": "Yahoo",
    "contact_person": "(權責範圍:汽百PM) 魏鈺哲 Joei",
    "phone": "(02)2360-3245",
    "extension": "",
    "mobile": "",
    "email": "yu-che.wei@yahooinc.com",
    "note": ""
  },
  {
    "excel_row": 102,
    "platform": "Yahoo",
    "contact_person": "(權責範圍:生活家電PM) 張庭豪 Jerry",
    "phone": "(02)2360-2843",
    "extension": "",
    "mobile": "0905-867211",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 104,
    "platform": "Yahoo",
    "contact_person": "(廠商服務窗口) 張祐毓",
    "phone": "(02)2360-3225",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 105,
    "platform": "Yahoo",
    "contact_person": "(廠商服務窗口) 彭蘭英Alan",
    "phone": "(02)2360-3210",
    "extension": "",
    "mobile": "",
    "email": "alanpeng@yahooinc.com",
    "note": ""
  },
  {
    "excel_row": 110,
    "platform": "Yahoo",
    "contact_person": "(帳務) 陳盈佳",
    "phone": "(02)2360-2340",
    "extension": "",
    "mobile": "",
    "email": "elva.chen@yahooinc.com",
    "note": ""
  },
  {
    "excel_row": 111,
    "platform": "Yahoo",
    "contact_person": "(發票申請) 陳靜珍",
    "phone": "(02)2360-2321",
    "extension": "",
    "mobile": "",
    "email": "ella1827@oath.com",
    "note": ""
  },
  {
    "excel_row": 112,
    "platform": "Yahoo",
    "contact_person": "(發票申請) 蔡孟珊",
    "phone": "(02)2360-2286",
    "extension": "2286",
    "mobile": "",
    "email": "sunny1@oath.com",
    "note": ""
  },
  {
    "excel_row": 113,
    "platform": "Yahoo",
    "contact_person": "(仲信資融) 郭芝綾",
    "phone": "(02)2798-6488",
    "extension": "75396",
    "mobile": "",
    "email": "",
    "note": "傳真(02)2798-6909\n應於機車商品出貨後，於登載系統出貨日前將註明訂金訂單編號之行車執照影本交付仲信資融"
  },
  {
    "excel_row": 120,
    "platform": "momo",
    "contact_person": "(招商) 李睿哲 Jack",
    "phone": "(02)2162-6688",
    "extension": "3532",
    "mobile": "0916-661388",
    "email": "jhli@fmt.com.tw",
    "note": "LINE: jack780827\nFAX：(02)2162-6696\n地址：11493台北市內湖區洲子街96號4樓"
  },
  {
    "excel_row": 121,
    "platform": "momo",
    "contact_person": "(MD) 邱宇弘",
    "phone": "(02)2162-6688",
    "extension": "3521",
    "mobile": "",
    "email": "",
    "note": "FAX：(02)2162-6696\n地址：11493台北市內湖區洲子街96號4樓"
  },
  {
    "excel_row": 122,
    "platform": "momo",
    "contact_person": "(PM) 林琮紫",
    "phone": "(02)2162-6688",
    "extension": "3570",
    "mobile": "",
    "email": "",
    "note": "FAX：(02)2162-6696\n地址：11493台北市內湖區洲子街96號4樓"
  },
  {
    "excel_row": 123,
    "platform": "momo",
    "contact_person": "(PM) 曾于甯",
    "phone": "(02)2162-6688",
    "extension": "3514",
    "mobile": "",
    "email": "",
    "note": "FAX：(02)2162-6696\n地址：11493台北市內湖區洲子街96號4樓"
  },
  {
    "excel_row": 124,
    "platform": "momo",
    "contact_person": "廠服",
    "phone": "(02)6600-7600",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 125,
    "platform": "momo",
    "contact_person": "客服",
    "phone": "0800-777959",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 126,
    "platform": "momo",
    "contact_person": "帳務 林小姐",
    "phone": "(02)2162-6688",
    "extension": "1191",
    "mobile": "mo+/1246",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 127,
    "platform": "台塑購物網",
    "contact_person": "PM 王樂瑋",
    "phone": "(02)2712-2211",
    "extension": "7091/7856",
    "mobile": "0975-913858",
    "email": "sellcrm@fpg.com.tw",
    "note": "FAX: (02)2718-9130"
  },
  {
    "excel_row": 128,
    "platform": "燦坤",
    "contact_person": "(商品PM、活動洽談) 蔡宗憲 Jacky",
    "phone": "(02)7720-3999",
    "extension": "11223",
    "mobile": "",
    "email": "jacky_tsai@tk3c.com",
    "note": "114 台北市內湖區堤頂大道一段331號5樓"
  },
  {
    "excel_row": 129,
    "platform": "燦坤",
    "contact_person": "(商品PM、活動洽談) 盧程鈞",
    "phone": "(02)7720-3999",
    "extension": "11509",
    "mobile": "",
    "email": "king_lu@tk3c.com",
    "note": "114 台北市內湖區堤頂大道一段331號5樓"
  },
  {
    "excel_row": 131,
    "platform": "燦坤",
    "contact_person": "(淨利紀律中心) 林怡萱",
    "phone": "(02)7720-3999",
    "extension": "11130",
    "mobile": "",
    "email": "vivian_lin@tk3c.tsannkuen.com",
    "note": "114臺北市內湖區提頂大道一段331號5樓 FAX: (02)8791-0868"
  },
  {
    "excel_row": 132,
    "platform": "燦坤",
    "contact_person": "(營運) 楊啟宏",
    "phone": "(02)7720-3999",
    "extension": "11102",
    "mobile": "",
    "email": "chihung_yang@kuai3.com.tw",
    "note": ""
  },
  {
    "excel_row": 133,
    "platform": "燦坤",
    "contact_person": "(商品上下架 助理) 郭冠彣",
    "phone": "(02)7720-3999",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 134,
    "platform": "燦坤",
    "contact_person": "(發票) 蔡明潔",
    "phone": "(02)7720-3999",
    "extension": "10800",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 135,
    "platform": "燦坤",
    "contact_person": "(會計) 陳常勻",
    "phone": "(02)7720-3999",
    "extension": "10603",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 137,
    "platform": "蔡家國際",
    "contact_person": "會計/出貨 黃小姐",
    "phone": "(02)2351-3290",
    "extension": "1028",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 138,
    "platform": "蔡家國際",
    "contact_person": "老闆娘-蔡小姐",
    "phone": "",
    "extension": "",
    "mobile": "0925-112695",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 139,
    "platform": "露天拍賣",
    "contact_person": "總機",
    "phone": "(02)5577-7700",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 140,
    "platform": "露天拍賣",
    "contact_person": "客服電話",
    "phone": "(02)5558-9168",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 141,
    "platform": "PchomePay支付連",
    "contact_person": "客服電話",
    "phone": "(02)2700-5066",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 142,
    "platform": "沐集購",
    "contact_person": "(業務副總) 呂立仁",
    "phone": "(02)2555-2828\n(02)2556-7272",
    "extension": "61",
    "mobile": "0932-080305",
    "email": "alanxp8888@gmail.com",
    "note": ""
  },
  {
    "excel_row": 143,
    "platform": "沐集購",
    "contact_person": "亭元",
    "phone": "",
    "extension": "",
    "mobile": "0930-000417",
    "email": "loveq987557@gmail.com",
    "note": ""
  },
  {
    "excel_row": 144,
    "platform": "三立電電購",
    "contact_person": "主管 兼PM 邵允康",
    "phone": "(02)8792-8888",
    "extension": "83033",
    "mobile": "0929-007428",
    "email": "kong.shao@mail.sanlih.com.tw",
    "note": "傳真 (02)2792-7073"
  },
  {
    "excel_row": 146,
    "platform": "三立電電購",
    "contact_person": "會計 華國媛",
    "phone": "(02)8792-8888",
    "extension": "83032",
    "mobile": "",
    "email": "",
    "note": "傳真 (02)2792-7073"
  },
  {
    "excel_row": 147,
    "platform": "三立電電購",
    "contact_person": "※出/退/換貨作業/客訴 黃鈺惠",
    "phone": "(02)8792-8888",
    "extension": "83014",
    "mobile": "",
    "email": "hardes@mail.sanlih.com.tw",
    "note": ""
  },
  {
    "excel_row": 148,
    "platform": "三立電電購",
    "contact_person": "※供應商資料及帳號密碼設定 施沛均",
    "phone": "(02)8792-8888",
    "extension": "83008\n83002",
    "mobile": "",
    "email": "maggieshih@mail.sanlih.com.tw",
    "note": ""
  },
  {
    "excel_row": 149,
    "platform": "生活市集",
    "contact_person": "PM 鄭梓謙 Brian",
    "phone": "(02)2655-2939",
    "extension": "",
    "mobile": "",
    "email": "brian.zheng@kuobrothers.com",
    "note": ""
  },
  {
    "excel_row": 150,
    "platform": "家樂福商城",
    "contact_person": "PM 呂春輝 Jack",
    "phone": "(02)2620-8299",
    "extension": "",
    "mobile": "0958-933233",
    "email": "",
    "note": "總機：(02)2898-1999 分機 8299\n傳真：(02)2895-2092\n地址：台北市北投區大業路136號5樓\n統編：22662550"
  },
  {
    "excel_row": 151,
    "platform": "蝦皮",
    "contact_person": "客服中心",
    "phone": "(02)6636-6559",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 152,
    "platform": "Coupang 酷澎",
    "contact_person": "商城AM 專員 James 陳奕軒",
    "phone": "(02)7751-5656",
    "extension": "5127",
    "mobile": "0958-329882",
    "email": "yichen50@coupang.com",
    "note": "台北市信義區信義路五段7號13樓\n統編：91002999"
  },
  {
    "excel_row": 153,
    "platform": "Coupang 酷澎",
    "contact_person": "商城AM 專員 殷先生",
    "phone": "(02)7751-5656",
    "extension": "",
    "mobile": "0913-991686",
    "email": "tzyin@coupang.com",
    "note": ""
  },
  {
    "excel_row": 154,
    "platform": "Coupang 酷澎",
    "contact_person": "商城客戶經理 Annie Yen",
    "phone": "(02)7751-5656",
    "extension": "5183",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 155,
    "platform": "Coupang 酷澎",
    "contact_person": "賣家支援中心",
    "phone": "(02)5592-7298、(02)5592-7598",
    "extension": "",
    "mobile": "",
    "email": "",
    "note": ""
  },
  {
    "excel_row": 156,
    "platform": "Coupang 酷澎",
    "contact_person": "採購團隊",
    "phone": "",
    "extension": "",
    "mobile": "",
    "email": "grp_cptaiwan_bmf@coupang.com",
    "note": ""
  },
  {
    "excel_row": 167,
    "platform": "蝦皮",
    "contact_person": "PM 林芯語",
    "phone": "",
    "extension": "",
    "mobile": "0918384199",
    "email": "joya.lin@shopee.com",
    "note": ""
  }
]'''
)


def import_network_platform_contacts(apps, schema_editor):
    SalesSource = apps.get_model("sales", "SalesSource")
    SalesSourceCategory = apps.get_model("sales", "SalesSourceCategory")
    PlatformContact = apps.get_model("sales", "SalesSourcePlatformContact")

    category = SalesSourceCategory.objects.filter(
        system_behavior="platform",
        name="網路平台",
    ).first()
    if category is None:
        category = SalesSourceCategory.objects.create(
            name="網路平台",
            system_behavior="platform",
            active=True,
        )

    sources = {}
    for item in CONTACT_ROWS:
        platform_name = item["platform"]
        source = sources.get(platform_name)
        if source is None:
            source = SalesSource.objects.filter(
                source_type="platform",
                name=platform_name,
            ).first()
            if source is None:
                source = SalesSource.objects.create(
                    source_type="platform",
                    category_id=category.pk,
                    name=platform_name,
                    active=True,
                )
            else:
                updates = {}
                if source.category_id is None:
                    updates["category_id"] = category.pk
                generic_note = f"歷史聯絡資料：{source.name}（負責人）"
                if source.responsible_person.strip() == source.name:
                    updates["responsible_person"] = ""
                if source.note.strip() == generic_note:
                    updates["note"] = ""
                if updates:
                    SalesSource.objects.filter(pk=source.pk).update(**updates)
                    for field_name, value in updates.items():
                        setattr(source, field_name, value)
            sources[platform_name] = source

        lookup = {
            "source_id": source.pk,
            "contact_person": item["contact_person"],
            "phone": item["phone"],
            "extension": item["extension"],
            "mobile": item["mobile"],
            "email": item["email"],
        }
        contact, created = PlatformContact.objects.get_or_create(
            **lookup,
            defaults={
                "note": item["note"],
                "active": True,
                "display_order": item["excel_row"],
            },
        )
        if not created:
            updates = {}
            if contact.note != item["note"]:
                updates["note"] = item["note"]
            if not contact.active:
                updates["active"] = True
            if contact.display_order != item["excel_row"]:
                updates["display_order"] = item["excel_row"]
            if updates:
                PlatformContact.objects.filter(pk=contact.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0103_network_platform_contacts"),
    ]

    operations = [
        migrations.RunPython(
            import_network_platform_contacts,
            migrations.RunPython.noop,
        ),
    ]
