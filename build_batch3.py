#!/usr/bin/env python3
"""Build batch3_questions.txt from extracted MCQ data."""

import os, re, json

# ===================== RAW EXTRACTED DATA =====================
# Format: list of (page, qnum, qtext, optA, optB, optC, optD, correct)
raw_questions = []

def parse_pipe_line(line):
    """Parse a pipe-delimited question line."""
    parts = line.strip().split('|')
    if len(parts) >= 7:
        qnum = parts[0].strip()
        qtext = parts[1].strip()
        optA = parts[2].strip()
        optB = parts[3].strip()
        optC = parts[4].strip()
        optD = parts[5].strip()
        correct = parts[6].strip()[-1] if parts[6].strip() else ''
        return (qnum, qtext, optA, optB, optC, optD, correct)
    return None

# ===================== PAGE DATA =====================
# Each entry: page_number, topic_id, lines

page_data = []

# Page 56 - General Science (Physics Q1-7=18, Chemistry Q8-13=18, Biology Q14-20=17)
# Using 18 as default for mixed science
page56_lines = [
    "1|एक अवतल दर्पण की वक्रता त्रिज्या 30 सेमी है। इसकी फोकस दूरी होगी-| -10 सेमी| -15 सेमी| -30 सेमी| -60 सेमी|B",
    "2|किसी दर्पण से आप चाहे कितनी ही दूर खड़े हों, आपका प्रतिबिंब सदैव सीधा प्रतीत होता है। संभवतः दर्पण है-| केवल समतल| केवल अवतल| केवल उत्तल| या तो समतल अथवा उत्तल|D",
    "3|किसी शब्दकोश (dictionary) में पाए गए छोटे अक्षरों को पढ़ते समय आप निम्न में से कौन-सा लेंस पसंद करेंगे?| 50 सेमी फोकस दूरी का एक उत्तल लेंस| 50 सेमी फोकस दूरी का एक अवतल लेंस| 5 सेमी फोकस दूरी का एक उत्तल लेंस| 5 सेमी फोकस दूरी का एक अवतल लेंस|C",
    "4|एक स्वस्थ नेत्र के लिए स्पष्ट दृष्टि की न्यूनतम दूरी होती है-| 25 सेमी| 50 सेमी| 100 सेमी| अनंत|A",
    "5|एक स्वस्थ आँख के लिए दूर बिंदु होता है-| 25 सेमी पर| 50 सेमी पर| 100 सेमी पर| अनंत पर|D",
    "6|आकाश का रंग नीला दिखाई देता है-| प्रकाश के परावर्तन के कारण| प्रकाश के अपवर्तन के कारण| प्रकाश के प्रकीर्णन के कारण| पूर्ण आंतरिक परावर्तन के कारण|C",
    "7|वैद्युत शक्ति का मात्रक होता है-| वोल्ट| वाट| एम्पियर| ओम|B",
    "8|निम्न में से कौन-सा भौतिक परिवर्तन नहीं है?| जल का उबलकर जलवाष्प बनना| बर्फ का पिघलकर जल बनना| जल में नमक का घुलना| द्रवित पेट्रोलियम गैस (LPG) का दहन|D",
    "9|किसी रासायनिक अभिक्रिया में भाग लेने वाले पदार्थ कहलाते हैं-| उत्पाद| अभिकारक| उत्प्रेरक| इनमें से कोई नहीं|B",
    "10|Zn + H2SO4 -> ZnSO4 + H2 ऊपर दी गई अभिक्रिया है-| संयोजन अभिक्रिया| वियोजन अभिक्रिया| विस्थापन अभिक्रिया| द्विविस्थापन अभिक्रिया|C",
    "11|अम्लीय विलयन का pH मान है-| 7| 7 से कम| 7 से अधिक| शून्य|B",
    "12|धावन सोडा का रासायनिक सूत्र है-| NaOH| Na2CO3.10H2O| NaHCO3| CaOCl2|B",
    "13|निम्न में से कौन-सी अधातु है?| Zn| H| Mg| Na|B",
    "14|वृक्कों का कार्य है-| श्वसन| परिवहन| उत्सर्जन| पोषण|C",
    "15|पत्तियों पर कलियाँ विकसित होती हैं-| पुदीने में| आलू में| ब्रायोफिलम में| इन सभी में|C",
    "16|आनुवंशिक विज्ञान के जनक हैं-| एच. जे. मुलर| चार्ल्स डार्विन| ग्रेगर जॉन मेंडल| जे. डी. वाटसन|C",
    "17|दो डी.एन.ए. तंतु आपस में जुड़े होते हैं-| पेप्टाइड बंध द्वारा| सहसंयोजी बंध द्वारा| ग्लाइकोसिडिक बंध द्वारा| हाइड्रोजन बंध द्वारा|D",
    "18|मुकुलन (Budding) द्वारा प्रजनन होता है-| हाइड्रा में| केंचुआ में| तिलचट्टा में| कबूतर में|A",
    "19|मेंडल के अनुसार मटर के शुद्ध लंबे पौधे का जीन प्रारूप होता है-| TT| Tt| tt| tT|A",
    "20|निम्नलिखित में से कौन-सा एक मानव में मादा जनन तंत्र का भाग नहीं है?| अंडाशय| गर्भाशय| शुक्रवाहिका| डिंबवाहिनी|C"
]
# Q1-7 Physics, Q8-13 Chemistry, Q14-20 Biology -> use 18 for all (science)
for i, line in enumerate(page56_lines):
    p = parse_pipe_line(line)
    if p:
        # Q1-7 Physics=18, Q8-13 Chemistry=18, Q14-20 Biology -> use 18
        raw_questions.append((56, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 57 - Operating Systems (topic 34)
page57_lines = [
    "13|Which of the following is not an operating system?|Windows|Linux|Oracle|DOS|C",
    "14|BIOS is used by-|Operating system|Compiler|Interpreter|Application software|A",
    "15|What is the full form of BIOS?|Basic Input Output System|Binary Input Output System|Basic Input Off System|None of these|A",
    "16|Which of the following is a system software?|Device Driver|Word Processor|Spreadsheet|Web Browser|A",
    "17|Which of the following is the main function of the operating system?|Memory management|Process management|Disk and file management|All of the above|D",
    "18|What is the shortcut key to open the Run dialog box in Windows?|Win + R|Win + E|Win + D|Win + L|A",
    "19|Which command is used to display the version of MS-DOS?|VER|VERSION|CLS|DIR|A",
    "20|Which of the following is a multi-user operating system?|UNIX|MS-DOS|Windows 95|Windows 98|A",
    "21|Which file is used to boot MS-DOS?|COMMAND.COM|IO.SYS|MSDOS.SYS|All of the above|D",
    "22|What is the full form of FAT?|File Allocation Table|File Access Table|File Activity Table|File Allotment Table|A"
]
for line in page57_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((57, 34, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 58 - Mixed CS topics
page58_topic_map = {
    24: 37, 25: 25, 26: 34, 27: 35, 28: 27, 29: 25, 30: 41,
    31: 33, 32: 33, 33: 37, 34: 35, 35: 39
}
page58_lines = [
    "24|With respect to multimedia, the term SNR stands for:|Signal with Noise Rate|Signal to Noise Rate|Signal and Noise Rate|Signal to Noise Ratio|D",
    "25|Which of the following category of ports is generally used to connect a monitor to a computer's video card?|Serial port|VGA port|Parallel port|PS/2 port|B",
    "26|Which of the following is NOT a cause of system hang?|Presence of virus|None of these|Excess power supply|Execution of corrupted file|C",
    "27|NIC is a hardware component which is used to connect one computer to another computer in a network. What is the meaning of the term NIC?|New Interface Card|Network interface Care|Network Interface Card|Network integration Card|C",
    "28|You can set to include in every slide.|Date and Time|All of these|Footer|Slide Number|B",
    "29|Which of the following provides the slot to connect graphics cards?|RAM slot|AGP slot|USB port|PCI slot|B",
    "30|Which of the following is a part of the CPU of a computer?|Motherboard|ALU|SRAM|DRAM|B",
    "31|What is the full form of SQL?|Simple Query Language|Structured Queuing Language|Structured Query Language|Structured Queuing Lexicon|C",
    "32|Which of the following are not SQL DDL commands?|CREATE VIEW|CREATE SCHEMA, CREATE TABLE, ALTER TABLE|UNION, INTERSECT and EXCEPT|DROP TABLE, CREATE INDEX, DROP INDEX|C",
    "33|What will be the output of the following PHP code? <?php define('GREETING', 'PHP is a scripting language'); echo $GREETING; ?>|no output|error|$GREETING|PHP is a scripting language|B",
    "34|Which protocol provides e-mail facility among different hosts?|FTP|SMTP|TELNET|SNMP|B",
    "35|What is the name of the first recognized IoT device?|Smart Watch|ATM|Radio|Video game|B"
]
for line in page58_lines:
    p = parse_pipe_line(line)
    if p:
        qnum = int(p[0])
        tid = page58_topic_map.get(qnum, 25)
        raw_questions.append((58, tid, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 59 - Law/Polity (use 14 - Polity)
page59_lines = [
    "118|Which of the following belongs to a 'Project' under the UP Apartment Act, 2010?|Constructing any building|Making any addition to any building|Making any alteration in any building|All of the above|D",
    "119|Section 13 of the UP Apartment Act, 2010 deals with :|Contents of declaration|Declaration to be filed with the Competent Authority|Modification of declaration|None of the above|B",
    "120|The Uttar Pradesh Apartment (Promotion of Construction, Ownership and Maintenance) Act, 2010 came into force on :|22nd July, 2010|19th March, 2010|21st July, 2010|18th March, 2010|C",
    "121|Under UP Apartment Act, 2010, the definition of 'Promoter' is given under :|Section 3(m)|Section 3(o)|Section 3(u)|Section 3(v)|D",
    "122|Under UP Apartment Act, 2010, the definition of 'Common Areas and Facilities' is given under :|Section 3(g)|Section 3(h)|Section 3(i)|Section 3(j)|C",
    "123|The 'Competent Authority' under the UP Apartment Act, 2010 means :|Vice Chairman of Development Authority|District Magistrate|Both (a) and (b)|None of the above|C",
    "124|Under Section 14 of the UP Apartment Act, 2010, the Association of Apartment Owners is responsible for :|Management of common areas and facilities|Management of individual apartments|Both (a) and (b)|None of the above|A",
    "125|The provisions of the UP Apartment Act, 2010 apply to :|All buildings having four or more apartments|All buildings having two or more apartments|All buildings having six or more apartments|None of the above|A",
    "126|Under the UP Apartment Act, 2010, every person to whom any apartment is sold or transferred shall be :|Entitled to the exclusive ownership and possession of his apartment|Entitled to an undivided interest in the common areas and facilities|Both (a) and (b)|None of the above|C",
    "127|Under Section 12 of the UP Apartment Act, 2010, a declaration shall be submitted by :|Every promoter|Every apartment owner|The Association of Apartment Owners|None of the above|A",
    "128|Under the UP Apartment Act, 2010, 'Common Areas and Facilities' include :|The land on which the building is located|The foundations, columns, girders, beams, supports, main walls, roofs, halls, corridors, lobbies, stairs, stairways, fire-escapes, and entrances and exits of the building|The basements, cellars, yards, gardens, parking areas and storage spaces|All of the above|D",
    "129|Under the UP Apartment Act, 2010, every person to whom an apartment is transferred shall execute :|A deed of transfer|A declaration|Both (a) and (b)|None of the above|A",
    "130|Under Section 25 of the UP Apartment Act, 2010, the State Government may :|Make rules for carrying out the provisions of the Act|Give directions to the Development Authority|Both (a) and (b)|None of the above|A",
    "131|The UP Urban Planning and Development Act, 1973 came into force on :|15th August, 1973|31st October, 1973|2nd September, 1973|14th April, 1973|C",
    "132|The 'Development Authority' under the UP Urban Planning and Development Act, 1973 is a :|Body corporate|Government department|Society|None of the above|A",
    "133|Under the UP Urban Planning and Development Act, 1973, 'Development' means :|Carrying out of building, engineering, mining or other operations in, on, over or under land|Making of any material change in any building or land|Both (a) and (b)|None of the above|C",
    "134|Section 4 of the UP Urban Planning and Development Act, 1973 deals with :|Declaration of development areas|Constitution of the Development Authority|Master Plan for the development area|Zonal Development Plan|B",
    "135|The Master Plan under the UP Urban Planning and Development Act, 1973 shall be prepared by :|The Development Authority|The State Government|The District Magistrate|None of the above|A",
    "136|Under Section 13 of the UP Urban Planning and Development Act, 1973, the Development Authority may :|Amend the Master Plan|Amend the Zonal Development Plan|Both (a) and (b)|None of the above|C",
    "137|Under the UP Urban Planning and Development Act, 1973, no person shall undertake any development in a development area unless :|Permission has been obtained from the Vice-Chairman|The development is in accordance with the plans|Both (a) and (b)|None of the above|C"
]
for line in page59_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((59, 14, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 60 - GK/Geography (use 25 as catch-all for non-CS)
page60_topic_map = {
    114: 25, 115: 25, 116: 25, 117: 25, 118: 25, 119: 25, 120: 25, 121: 25,
    122: 25, 123: 25, 124: 25, 125: 25, 126: 25, 127: 25, 128: 25, 129: 25,
    130: 25, 131: 25, 132: 25, 133: 25
}
page60_lines = [
    "114|Which state has the largest area under forest cover?|Arunachal Pradesh|Haryana|Madhya Pradesh|Assam|C",
    "115|Which state of India has the lowest density of population according to the 2011 Census?|Meghalaya|Arunachal Pradesh|Mizoram|Sikkim|B",
    "116|What is the full form of MSME?|Micro, Small and Medium Enterprises|Medium, Small and Marginal Enterprises|Micro, Small and Marginal Enterprises|Minor, Small and Medium Enterprises|A",
    "117|In which year was the 'National Food Security Act' passed in India?|2011|2012|2013|2014|C",
    "118|Which city is known as the 'Electronic City of India'?|Hyderabad|Mumbai|Bengaluru|Chennai|C",
    "119|The 'Golden Quadrilateral' connects which of the following cities?|Delhi-Mumbai-Chennai-Kolkata|Delhi-Mumbai-Hyderabad-Kolkata|Delhi-Bengaluru-Chennai-Kolkata|Delhi-Mumbai-Chennai-Bengaluru|A",
    "120|Which river is known as the 'Dakshin Ganga'?|Krishna|Cauvery|Godavari|Mahanadi|C",
    "121|The 'Silent Valley National Park' is located in which state?|Tamil Nadu|Kerala|Karnataka|Andhra Pradesh|B",
    "122|Which of the following is the highest peak in South India?|Doddabetta|Anamudi|Mahendragiri|Kalsubai|B",
    "123|Which port is known as the 'Queen of the Arabian Sea'?|Mumbai|Kandla|Kochi|Vizag|C",
    "124|In India, 'Project Tiger' was launched in the year:|1970|1973|1980|1983|B",
    "125|Which state is the largest producer of tea in India?|West Bengal|Kerala|Assam|Tamil Nadu|C",
    "126|The 'Tehri Dam' is built on which river?|Alaknanda|Bhagirathi|Ganga|Yamuna|B",
    "127|Which pass connects Srinagar to Leh?|Nathu La|Bara-lacha La|Zoji La|Rohtang Pass|C",
    "128|The 'Kaziranga National Park' is famous for:|Lion|Tiger|One-horned Rhinoceros|Elephant|C",
    "129|Which is the longest irrigation canal in India?|Sirhind Canal|Indira Gandhi Canal|Yamuna Canal|Upper Bari Doab Canal|B",
    "130|The 'Jog Falls' is situated on which river?|Sharavati|Cauvery|Krishna|Godavari|A",
    "131|Which state is known as the 'Spice Garden of India'?|Karnataka|Tamil Nadu|Kerala|Andhra Pradesh|C",
    "132|The 'Hirakud Dam' is located on which river?|Mahanadi|Godavari|Cauvery|Krishna|A",
    "133|Which is the oldest oil refinery in India?|Haldia|Koyali|Digboi|Mathura|C"
]
for line in page60_lines:
    p = parse_pipe_line(line)
    if p:
        qnum = int(p[0])
        tid = page60_topic_map.get(qnum, 25)
        raw_questions.append((60, tid, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 61 - Physics/Electricity (topic 18)
page61_lines = [
    "37|विद्युत प्रतिरोध की माप की इकाई क्या है?|वोल्ट|एम्पीयर|ओम|वॉट|C",
    "38|किसी भी संवाहक के प्रतिरोध में क्या परिवर्तन होगा यदि इसके अनुप्रस्थ काट के क्षेत्रफल को दोगुना कर दिया जाए?|प्रतिरोध दोगुना हो जाता है|प्रतिरोध आधा हो जाता है|प्रतिरोध चार गुना हो जाता है|प्रतिरोध में कोई परिवर्तन नहीं होता|B",
    "39|यदि किसी संवाहक के अनुप्रस्थ काट के क्षेत्रफल को दोगुना कर दिया जाए, तो इसका प्रतिरोध ........... हो जाएगा।|आधा|दोगुना|चार गुना|एक-चौथाई|A",
    "40|विद्युत प्रतिरोधकता का SI मात्रक क्या है?|ओम-मीटर|एम्पीयर|ओम|वोल्ट|A",
    "41|प्रतिरोध का SI मात्रक क्या है?|ओम|कूलाम|जूल|न्यूटन|A",
    "42|किसी चालक का प्रतिरोध इसकी ........... के व्युत्क्रमानुपाती होता है।|लंबाई|प्रतिरोधकता|अनुप्रस्थ भाग का क्षेत्रफल|तापमान|C",
    "43|ओम के नियम के अनुसार, यदि धारा (I) बढ़ती है और विभवांतर (V) स्थिर रहता है, तो:|प्रतिरोध बढ़ता है|प्रतिरोध कम होता है|प्रतिरोध स्थिर रहता है|धारा और विभवांतर के बीच कोई संबंध नहीं है|B",
    "44|R = V/I नियम को क्या कहा जाता है?|ओम का नियम|फैराडे का नियम|कूलाम का नियम|न्यूटन का नियम|A",
    "45|निम्नलिखित में से कौन सा घटक एक विद्युत परिपथ में धारा की मात्रा को नियंत्रित करता है बिना वोल्टता के स्रोत को बदले?|प्रतिरोधक|वोल्टमीटर|एमीटर|परिवर्ती प्रतिरोध|D",
    "46|विद्युत परिपथ में ........... का प्रयोग परिपथ में धारा को नियंत्रित करने के लिए किया जाता है।|वोल्टमीटर|गैल्वेनोमीटर|रियोस्टेट|एमीटर|C",
    "47|जब दो या दो से अधिक प्रतिरोधों को एक के बाद एक (End-to-end) जोड़ा जाता है, तो वे ........... जुड़े होते हैं।|श्रेणीक्रम|समानांतर|उपर्युक्त दोनों|इनमें से कोई नहीं|A",
    "48|जब कई प्रतिरोधों को श्रेणीक्रम में जोड़ा जाता है, तो प्रत्येक प्रतिरोध में धारा का मान ........... रहता है।|समान|भिन्न|शून्य|अधिकतम|A",
    "49|विद्युत धारा की मात्रा को मापने के लिए किस उपकरण का उपयोग किया जाता है?|वोल्टमीटर|एमीटर|ओममीटर|गैल्वेनोमीटर|B",
    "50|एक सुचालक का प्रतिरोध निम्नलिखित में से किस कारक पर निर्भर नहीं करता है?|लंबाई|पदार्थ|दबाव|अनुप्रस्थ भाग का क्षेत्रफल|C",
    "51|ओम के नियम के अनुसार, ........... एक स्थिरांक है।|V/I|VI|V-I|I/V|A",
    "52|एक परिपथ में, कई प्रतिरोधक श्रृंखला में जुड़े हुए हैं, तो धारा का मान क्या होगा?|बढ़ता है|कम होता है|एक ही रहता है|आधा हो जाता है|C",
    "53|विभवांतर 12V और किया गया कार्य 60J है, परिपथ के माध्यम से प्रवाहित विद्युत आवेश क्या है?|5C|0.2C|720C|48C|A",
    "54|एक चालक का प्रतिरोध इसकी ........... के समानुपाती होता है।|अनुप्रस्थ भाग का क्षेत्रफल|लंबाई|घनत्व|आयतन|B",
    "55|ओम का नियम ........... और ........... के बीच संबंध का वर्णन करता है।|विद्युत आवेश और समय|विभवांतर और विद्युत धारा|विद्युत धारा और समय|विभवांतर और आवेश|B",
    "56|10 ओम के दो समान प्रतिरोधक समानांतर रूप से जुड़े हुए हैं। यह संयोजन 10 ओम के तीसरे प्रतिरोधक से जोड़ा जाता है। संयोजन का समकक्ष प्रतिरोध ........... के बराबर होगा।|15 ओम|5 ओम|25 ओम|10 ओम|A",
    "57|यदि दो प्रतिरोधक श्रृंखला में जुड़े हुए हैं, तो निम्नलिखित में से कौन सा कथन सही है?|प्रत्येक प्रतिरोधक के माध्यम से प्रवाहित होने वाली धारा समान होती है।|प्रत्येक प्रतिरोधक में विभवांतर समान होता है।|प्रतिरोधकों के माध्यम से धारा भिन्न होती है।|प्रतिरोधकों में विभवांतर का योग कुल विभवांतर के बराबर नहीं होता है।|A",
    "58|प्रतिरोध का SI मात्रक क्या है?|ओम|जूल|वोल्ट|एम्पीयर|A",
    "59|यदि एक सर्किट का प्रतिरोध दोगुना कर दिया जाता है, तो वोल्टेज को समान रखने के लिए, सर्किट में प्रवाहित धारा ...........।|आधी घट जाएगी|एक-चौथाई कम हो जाएगी|चार गुना बढ़ जाएगी|स्थिर रहेगी|A"
]
for line in page61_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((61, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 62 - Networking/Web (35=Networking, 37=Web)
page62_topic_map = {}
for qn in range(303, 314):
    page62_topic_map[qn] = 35  # Networking
for qn in range(314, 329):
    page62_topic_map[qn] = 37  # Web Technologies
page62_lines = [
    "303|Ethernet is -|LAN|MAN|WAN|All of these|A",
    "304|A set of rules that governs data communication is-|Protocol|Medium|Topology|Internet|A",
    "305|The full form of 'HTTP' is-|Hyper Text Transfer Protocol|Hyper Text Transfer Package|Hyper Transfer Text Protocol|Hyper Text Technical Protocol|A",
    "306|The full form of 'WWW' is-|World Wide Web|World With Web|World Wide Word|World Wide Website|A",
    "307|Which protocol is used for sending e-mails?|SMTP|HTTP|FTP|POP3|A",
    "308|The full form of 'URL' is-|Uniform Resource Locator|Universal Resource Locator|Uniform Remote Locator|Unique Resource Locator|A",
    "309|The full form of 'IP' is-|Internet Protocol|Internal Protocol|Internet Package|Internal Package|A",
    "310|What does '.com' mean in a domain name?|Commercial|Communication|Community|Common|A",
    "311|Which protocol is used for data communication on the internet?|TCP/IP|HTTP|FTP|SMTP|A",
    "312|Which device converts digital signals to analog signals?|Modem|Router|Switch|Hub|A",
    "313|Bluetooth is an example of-|PAN (Personal Area Network)|LAN|MAN|WAN|A",
    "314|What is used for writing web pages?|HTML|HTTP|FTP|URL|A",
    "315|The full form of 'Wi-Fi' is-|Wireless Fidelity|Wireless Fiber|Wireless Field|Wireless Finder|A",
    "316|Which protocol is used for file transfer?|FTP|HTTP|SMTP|TCP|A",
    "317|The physical arrangement of a network is called-|Topology|Protocol|Routing|Switching|A",
    "318|Which topology uses a central hub?|Star|Bus|Ring|Mesh|A",
    "319|How many bits is a MAC address?|48|32|64|128|A",
    "320|What is the internet?|Network of Networks|A software|A hardware|A website|A",
    "321|The full form of 'ISP' is-|Internet Service Provider|Internet Service Protocol|Internal Service Provider|Internal Service Protocol|A",
    "322|What does '.in' mean in a domain name?|India|Indonesia|Iran|Iraq|A",
    "323|Which search engine is developed by Microsoft?|Bing|Google|Yahoo|Baidu|A",
    "324|The full form of 'DNS' is-|Domain Name System|Domain Name Service|Domain Network System|Domain Network Service|A",
    "325|What is the function of a search engine?|Searching information|Sending email|Playing games|Chatting|A",
    "326|The main page of a website is called-|Home Page|Master Page|Index Page|Bookmark|A",
    "327|The full form of 'MODEM' is-|Modulator-Demodulator|Modulation-Demodulation|Modern-Demodulator|Mobile-Demodulator|A",
    "328|Which of the following is NOT a search engine?|Instagram|Google|Bing|Yahoo|A"
]
for line in page62_lines:
    p = parse_pipe_line(line)
    if p:
        qnum = int(p[0])
        tid = page62_topic_map.get(qnum, 35)
        raw_questions.append((62, tid, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 63 - History (use 25 as catch-all)
page63_lines = [
    "83|'शून्य' का आविष्कार किसने किया था?|आर्यभट्ट|वराहमिहिर|भास्कर|किसी अज्ञात भारतीय ने|A",
    "84|शून्य की खोज की:|भास्कर ने|आर्यभट्ट ने|वराहमिहिर ने|इनमें से कोई नहीं|B",
    "85|निम्नलिखित में से किस भारतीय गणितज्ञ ने दशमलव स्थानिक मान की खोज की थी?|भास्कर|वराहमिहिर|ब्रह्मगुप्त|आर्यभट्ट|D",
    "86|आर्यभट्ट थे:|भारतीय राजनीतिज्ञ|भारतीय गणितज्ञ एवं खगोलशास्त्री|भारतीय संस्कृत विद्वान एवं कवि|इनमें से कोई नहीं|B",
    "87|मतविलास प्रहसन का लेखक कौन था?|गौतमीपुत्र शातकर्णी|महाक्षत्रप रुद्रदामन|महेंद्रवर्मन|पुलकेशिन II|C",
    "88|'मतविलास प्रहसन' के लेखक थे-|हर्ष|राजशेखर|महेंद्रवर्मन|शिवस्कंदवर्मन|C",
    "89|महाबलीपुरम के 'रथ' मंदिरों का निर्माण किसने करवाया था?|नरसिंहवर्मन प्रथम ने|समुद्रगुप्त ने|हर्ष ने|पुलकेशिन II ने|A",
    "90|महाबलीपुरम में रथ मंदिरों का निर्माण कराया गया था-|चोलों द्वारा|पल्लवों द्वारा|चेदियों द्वारा|चालुक्यों द्वारा|B",
    "91|महाबलीपुरम के सप्त रथ मंदिर का निर्माण कराया था-|महेंद्रवर्मन द्वारा|नरसिंहवर्मन द्वारा|परमेश्वरवर्मन द्वारा|नंदीवर्मन द्वारा|B",
    "92|महाबलीपुरम का सप्तरथ मंदिर बनवाया गया था-|महेंद्रवर्मन द्वारा|नरसिंहवर्मन द्वारा|परमेश्वरवर्मन द्वारा|नंदीवर्मन द्वारा|B",
    "93|किस पल्लव शासक के शासनकाल में पल्लवों और चालुक्यों के बीच लंबा संघर्ष शुरू हो गया था?|महेंद्रवर्मन I|सिंहविष्णु|नरसिंहवर्मन I|महेंद्रवर्मन II|A",
    "94|किस गुप्त शासक ने श्रीलंकाई राजा मेघवर्मन को गया में एक बौद्ध मठ बनाने की अनुमति दी थी?|समुद्रगुप्त|कुमारगुप्त|स्कंदगुप्त|चंद्रगुप्त द्वितीय|A",
    "95|श्रीलंका के राजा मेघवर्मन ने किस स्थान पर भगवान बुद्ध का मंदिर बनाने के लिए समुद्रगुप्त से अनुमति माँगी थी?|कुशीनगर|बोधगया|सारनाथ|प्रयाग|B",
    "96|गुप्तकालीन रजत मुद्राओं को नाम दिया गया था-|कषार्पण|दीनार|रूपक|निष्क|C",
    "97|'रजत' सिक्के जारी करने वाला प्रथम गुप्त शासक था-|चन्द्रगुप्त I|समुद्रगुप्त|चन्द्रगुप्त II|कुमारगुप्त|C",
    "98|निम्नलिखित में से किस गुप्त शासक ने सर्वप्रथम सिक्के जारी किए?|श्रीगुप्त ने|चन्द्रगुप्त प्रथम ने|समुद्रगुप्त ने|चन्द्रगुप्त द्वितीय ने|B",
    "99|निम्नलिखित शासकों में से किस एक ने चार अश्वमेधों का सम्पादन किया था?|पुष्यमित्र शुंग|प्रवरसेन प्रथम|समुद्रगुप्त|चन्द्रगुप्त द्वितीय|B",
    "100|गुप्त राजा जिसने 'विक्रमादित्य' की पदवी ग्रहण की थी, वह था-|स्कन्दगुप्त|समुद्रगुप्त|चन्द्रगुप्त II|कुमारगुप्त|C",
    "101|परम भागवत उपाधि धारण करने वाला प्रथम गुप्त शासक था-|चन्द्रगुप्त I|समुद्रगुप्त|चन्द्रगुप्त II|रामगुप्त|B",
    "102|समुद्रगुप्त के प्रयाग प्रशस्ति वाले स्तंभ पर निम्नलिखित में से किसका लेख मिलता है?|जहाँगीर|शाहजहाँ|औरंगजेब|दारा शिकोह|A",
    "103|प्रयाग प्रशस्ति किसके सैन्य अभियान के बारे में जानकारी देता है?|चन्द्रगुप्त I|समुद्रगुप्त|चन्द्रगुप्त II|कुमारगुप्त|B",
    "104|'पृथ्वीव्या प्रथम वीर' उपाधि थी-|समुद्रगुप्त की|चन्द्रगुप्त प्रथम की|अमोधवर्ष की|गौतमीपुत्र शातकर्णी की|A"
]
for line in page63_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((63, 25, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 64 - Management/Decision Making -> 38 (SDLC/Management)
page64_lines = [
    "48|The process of identifying and choosing the best course of action from among several alternatives is known as|Planning|Decision-making|Organizing|Controlling|B",
    "49|Which of the following is the first step in the decision-making process?|Developing alternatives|Evaluating alternatives|Identifying the problem|Selecting an alternative|C",
    "50|Decisions that are repetitive and routine, and for which a definite procedure has been developed are called|Programmed decisions|Non-programmed decisions|Strategic decisions|Operational decisions|A",
    "51|The decision-making model which assumes that managers make rational decisions that maximize the organization's benefit is the|Administrative model|Rational model|Political model|Garbage can model|B",
    "52|The tendency of decision-makers to seek only information that supports their existing beliefs is known as|Hindsight bias|Confirmation bias|Anchoring bias|Escalation of commitment|B",
    "53|A technique used to generate a large number of creative ideas in a group setting is|Delphi technique|Brainstorming|Nominal group technique|Linear programming|B",
    "54|The concept of 'Bounded Rationality' was proposed by|F.W. Taylor|Henri Fayol|Herbert Simon|Max Weber|C",
    "55|Which type of decision involves high risk and uncertainty and is often unique and non-recurring?|Programmed decisions|Non-programmed decisions|Tactical decisions|Routine decisions|B",
    "56|Groupthink is most likely to occur in|Highly cohesive groups|Diverse groups|Small groups|Low-pressure environments|A",
    "57|The 'Delphi Technique' is primarily used for|Conflict resolution|Performance appraisal|Forecasting and expert consensus|Financial auditing|C"
]
for line in page64_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((64, 38, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 65 - Diesel Engine/Mechanical -> 18
page65_lines = [
    "92|डीजल इंजन में, पिस्टन की अधिकतम गति कहाँ होती है?|टी.डी.सी. पर|बी.डी.सी. पर|स्ट्रोक के मध्य में|उपरोक्त में से कोई नहीं|C",
    "93|पिस्टन रिंग्स आमतौर पर किस सामग्री की बनी होती हैं?|एल्युमिनियम|पीतल|कास्ट आयरन|स्टील|C",
    "94|पिस्टन रिंगों का मुख्य कार्य क्या है?|ईंधन जलाना|सिलेंडर को सील करना|तेल को ठंडा करना|गति को नियंत्रित करना|B",
    "95|गजन पिन (Gudgeon pin) किसे जोड़ती है?|पिस्टन और कनेक्टिंग रॉड|क्रैंकशाफ्ट और कनेक्टिंग रॉड|पिस्टन और क्रैंकशाफ्ट|उपरोक्त में से कोई नहीं|A",
    "96|कनेक्टिंग रॉड का छोटा सिरा (Small end) किससे जुड़ा होता है?|क्रैंकशाफ्ट|पिस्टन पिन|कैमशाफ्ट|फ्लाईव्हील|B",
    "97|कनेक्टिंग रॉड का बड़ा सिरा (Big end) किससे जुड़ा होता है?|पिस्टन|क्रैंक पिन|गजन पिन|उपरोक्त में से कोई नहीं|B",
    "98|क्रैंकशाफ्ट का मुख्य कार्य क्या है?|रैखिक गति को रोटरी गति में बदलना|रोटरी गति को रैखिक गति में बदलना|ईंधन पंप करना|उपरोक्त में से कोई नहीं|A",
    "99|फ्लाईव्हील कहाँ लगा होता है?|पिस्टन पर|कनेक्टिंग रॉड पर|क्रैंकशाफ्ट पर|कैमशाफ्ट पर|C",
    "100|कैमशाफ्ट का कार्य क्या है?|वॉल्व खोलना और बंद करना|पिस्टन को घुमाना|तेल पंप करना|उपरोक्त में से कोई नहीं|A",
    "101|4-स्ट्रोक इंजन में, कैमशाफ्ट की गति क्रैंकशाफ्ट की गति की कितनी होती है?|समान|आधी|दुगुनी|चार गुनी|B",
    "102|सिलेंडर हेड आमतौर पर किसका बना होता है?|कास्ट आयरन या एल्युमिनियम अलॉय|तांबा|प्लास्टिक|रबड़|A",
    "103|इंजन के वाल्व कहाँ स्थित होते हैं?|सिलेंडर ब्लॉक में|सिलेंडर हेड में|पिस्टन में|A और B दोनों|D",
    "104|डीजल इंजन में ईंधन कैसे इंजेक्ट किया जाता है?|कार्ब्युरेटर द्वारा|ईंधन इंजेक्टर द्वारा|स्पार्क प्लग द्वारा|उपरोक्त में से कोई नहीं|B",
    "105|संपीड़न अनुपात (Compression ratio) क्या है?|(Vs+Vc)/Vc|Vc/Vs|Vs/Vc|उपरोक्त में से कोई नहीं|A"
]
for line in page65_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((65, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 66 - Electronics -> 18
page66_lines = [
    "34|The maximum efficiency of a half wave rectifier is :|40.6%|81.2%|50%|100%|A",
    "35|The barrier potential for a silicon diode is approximately :|0.3 V|0.7 V|1.1 V|0 V|B",
    "36|In full wave rectifier, if input frequency is 50 Hz, then output ripple frequency will be :|50 Hz|100 Hz|150 Hz|200 Hz|B",
    "37|A Zener diode is used as :|An amplifier|A voltage regulator|A rectifier|A filter|B",
    "38|The reverse current in a silicon P-N junction diode is in the order of :|mA|uA|nA|A|C",
    "39|The depletion layer of a P-N junction diode contains :|Electrons|Holes|Immobile ions|Both (a) and (b)|C",
    "40|A transistor is a :|Current controlled device|Voltage controlled device|Power controlled device|None of these|A",
    "41|The decimal equivalent of (1101)2 is :|11|12|13|14|C",
    "42|Which of the following is a universal gate?|OR gate|AND gate|NAND gate|NOT gate|C",
    "43|Ripple factor of a full wave rectifier is :|0.48|1.21|0.82|1.11|A",
    "44|In common emitter configuration, the current gain is :|Alpha|Beta|Gamma|None of these|B",
    "45|The process of adding impurities to a pure semiconductor is called :|Doping|Diffusing|Drifting|Ionization|A",
    "46|Peak inverse voltage of a half wave rectifier is :|Vm|2Vm|Vm/2|sqrt2 Vm|A",
    "47|In a bridge rectifier, the number of diodes used is :|1|2|3|4|D",
    "48|The efficiency of a full wave rectifier is :|40.6%|81.2%|50%|100%|B",
    "49|A ripple factor is defined as :|Irms/Idc|Vrms/Vdc|r = sqrt((Irms/Idc)2 - 1)|None of these|C"
]
for line in page66_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((66, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 67 - GK/Mixed -> 25
page67_lines = [
    "218|When is the 'World Soil Day' observed every year?|7 December|5 December|3 December|1 December|B",
    "219|Who among the following was the last ruler of the Lodi Dynasty?|Bahlul Lodi|Ibrahim Lodi|Daulat Khan Lodi|Sikandar Lodi|B",
    "220|Who was the first ever female Secretary General of SAARC?|Madeleine Albright|Antonio Guterres|Fathimath Dhiyana Saeed|Jeremiah Manele|C",
    "221|The 'Paitkar' painting is a unique cultural symbol of ______ .|Jharkhand|Chhattisgarh|Telangana|Karnataka|A",
    "222|The ______ , which is a link between the Himalayan range and the Shivalik hills, is the entry point of many rivers into the Haryana plains.|Ambala Range|Morni Hills|Aravalli Hills|Nahan|B",
    "223|Who won the 'Player of the Tournament' award in the 2019 ICC World Cup?|Ben Stokes|Kane Williamson|Rohit Sharma|Mitchell Starc|B",
    "224|Which of the following describes the 'Loo'?|Summer breeze in coastal areas|Cold wind|Heat wave|Icy wind|C",
    "225|In terms of area, which is the smallest Union Territory of India?|Daman and Diu|Puducherry|Dadra and Nagar Haveli|Lakshadweep|D",
    "226|Which is the only state of India that produces saffron?|Himachal Pradesh|Assam|Jammu and Kashmir|Meghalaya|C",
    "227|In terms of the size of the planets, Saturn ranks ______ in our solar system.|1st|2nd|3rd|4th|B",
    "228|Which of the following is the most ductile metal?|Gold|Aluminium|Copper|Silver|A",
    "229|In which state is the Kaziranga National Park situated?|Assam|Bihar|Madhya Pradesh|Rajasthan|A",
    "230|Which of the following is NOT a fundamental right under the Indian Constitution?|Right to Equality|Right against Exploitation|Right to Property|Right to Freedom of Religion|C",
    "231|The famous Sun Temple at Konark was built by ______ .|Narasimhadeva I|Rajendra Chola|Ashoka|Kanishka|A",
    "232|What is the SI unit of power?|Joule|Watt|Newton|Pascal|B",
    "233|The 'Quit India Movement' was started in which year?|1930|1932|1942|1945|C",
    "234|Which of the following gases is most abundant in the Earth's atmosphere?|Oxygen|Carbon dioxide|Nitrogen|Hydrogen|C",
    "235|Who is the author of the book 'The Discovery of India'?|Mahatma Gandhi|Jawaharlal Nehru|Sardar Patel|Subhas Chandra Bose|B"
]
for line in page67_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((67, 25, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 68 - Computer Storage/Fundamentals + Number Systems -> 25
page68_topic_map = {}
for qn in range(118, 148):
    page68_topic_map[qn] = 25  # Storage/Fundamentals
page68_topic_map[148] = 26  # Binary
page68_topic_map[149] = 26  # Octal
page68_topic_map[150] = 26  # Hex
page68_topic_map[151] = 25  # BIT
page68_topic_map[152] = 25  # Nibble
page68_topic_map[153] = 25  # MB-KB
page68_topic_map[154] = 25  # GB
page68_topic_map[155] = 25  # Data unit
page68_topic_map[156] = 25  # Largest unit
page68_lines = [
    "118|किसी संचयन माध्यम के वृत्त का वह हिस्सा जिस पर आंकड़े लिखे जाते हैं, कहलाता है-|डिस्क|ड्राइव|सेक्टर|सिलेंडर|C",
    "119|हार्ड डिस्क में विभिन्न संचयन क्षेत्रों को क्या कहा जाता है?|सेक्टर|कैस्केड|कलस्टर्स|ट्रैक्स|D",
    "120|ट्रैक का एक हिस्सा जिस पर डेटा संग्रहीत किया जाता है, कहलाता है-|सेक्टर|कलस्टर|स्लॉट|उपर्युक्त में से कोई नहीं|A",
    "121|फ्लॉपी डिस्क में डेटा ......... नामक रिंग्स पर रिकॉर्ड किया जाता है।|ट्रैक्स|सेक्टर्स|रिंगर्स|राउंडर्स|A",
    "122|कंप्यूटर में डेटा को मुख्य रूप से संग्रहीत करने के लिए निम्नलिखित में से किस उपकरण का उपयोग किया जाता है?|मॉनिटर|माउस|हार्ड डिस्क|कीबोर्ड|C",
    "123|कम्प्यूटर शब्दावली में एचडीडी का अर्थ क्या है?|हार्ड डिस्क ड्राइव|हाई डिस्क ड्राइव|हाइब्रिड डिस्क ड्राइव|हॉट डिस्क ड्राइव|A",
    "124|एक डिस्क का वह हिस्सा जो वृत्ताकार पथ बनाता है, कहलाता है-|सेक्टर|ट्रैक|क्लस्टर|सिलेंडर|B",
    "125|मैग्नेटिक डिस्क की सतह पर सूचनाएं संचित की जाती हैं-|कॉनसेंट्रिक ट्रैक्स में|सेक्टर्स में|ए और बी दोनों में|इनमें से कोई नहीं|C",
    "126|हार्ड डिस्क ड्राइव्स को ....... स्टोरेज माना जाता है।|फ्लैश|नॉन-वोलाटाइल|टेम्पररी|वोलाटाइल|B",
    "127|फ्लॉपी डिस्क में ....... सेक्टर होते हैं।|40|80|120|160|B",
    "128|फ्लॉपी डिस्क का उपयोग किस लिए किया जाता है?|डेटा पढ़ने के लिए|डेटा लिखने के लिए|सूचना संग्रहीत करने के लिए|उपर्युक्त सभी|D",
    "129|सीडी का पूर्ण रूप क्या है?|कॉम्पैक्ट डिस्क|कॉमन डिस्क|कम्प्यूटर डिस्क|कंट्रोल डिस्क|A",
    "130|एक कॉम्पैक्ट डिस्क में डेटा स्टोर करने के लिए किस तकनीक का उपयोग किया जाता है?|लेजर|मैग्नेटिक|इलेक्ट्रिकल|मैकेनिकल|A",
    "131|सीडी-आर का अर्थ है-|कॉम्पैक्ट डिस्क रीडेबल|कॉम्पैक्ट डिस्क रिकाॅर्डेबल|कॉम्पैक्ट डिस्क रीराइटेबल|उपर्युक्त में से कोई नहीं|B",
    "132|एक बाइट में कितने बिट्स होते हैं?|2|8|16|32|B",
    "133|कम्प्यूटर की शब्दावली में 'KB' का अर्थ है-|की-ब्लॉक|कर्नल-बूट|किलो-बाइट|किट-बिट|C",
    "134|कम्प्यूटर की स्मृति सामान्य तौर से किलोबाइट या मेगाबाइट के रूप में व्यक्त की जाती है। एक बाइट बना होता है-|आठ द्विआधारी अंकों का|दो द्विआधारी अंकों का|आठ दशमलव अंकों का|दो दशमलव अंकों का|A",
    "135|सबसे कम एक्सेस समय है-|कैश मेमरी|मैग्नेटिक बबल मेमरी|मैग्नेटिक कोर मेमरी|रैंडम एक्सेस मेमरी|A",
    "136|इनमें से कौन कम्प्यूटर की एक मुख्य मेमोरी है?|रैम|कैश|रोम|उपर्युक्त सभी|D",
    "137|रैम का पूर्ण रूप क्या है?|रीड एक्सेस मेमोरी|रैंडम एक्सेस मेमोरी|रीयल एक्सेस मेमोरी|रिमोट एक्सेस मेमोरी|B",
    "138|रोम क्या है?|रीड ओनली मेमोरी|रैंडम ओनली मेमोरी|रीयल ओनली मेमोरी|रिमोट ओनली मेमोरी|A",
    "139|द्वितीयक संचयन इकाई के रूप में भी जाना जाता है-|प्राइमरी मेमोरी|एक्सिलरी मेमोरी|कैश मेमोरी|रजिस्टर|B",
    "140|सीडी-रोम का पूर्ण रूप क्या है?|कॉम्पैक्ट डिस्क रीड ओनली मेमोरी|कॉम्पैक्ट डाटा रीड ओनली मेमोरी|कॉम्पैक्ट डिस्क रैंडम ओनली मेमोरी|कॉम्पैक्ट डाटा रैंडम ओनली मेमोरी|A",
    "141|फ्लॉपी डिस्क एक ....... है।|आउटपुट डिवाइस|इनपुट डिवाइस|स्टोरेज डिवाइस|बी और सी दोनों|D",
    "142|डीवीडी का पूर्ण रूप क्या है?|डिजिटल वीडियो डिस्क|डिजिटल वर्सेटाइल डिस्क|ए और बी दोनों|उपरोक्त में से कोई नहीं|C",
    "143|यूएसबी का पूर्ण रूप क्या है?|यूनिवर्सल सीरियल बस|यूनिवर्सल स्मार्ट बस|यूनाइटेड सीरियल बस|यूनाइटेड स्मार्ट बस|A",
    "144|फ्लैश मेमोरी एक प्रकार का ....... है।|ईईप्रोम|ईप्रोम|प्रोम|रैम|A",
    "145|बायोस का अर्थ है-|बेसिक इनपुट आउटपुट सिस्टम|बाइनरी इनपुट आउटपुट सिस्टम|बेसिक इंटरनल आउटपुट सिस्टम|बाइनरी इंटरनल आउटपुट सिस्टम|A",
    "146|पोस्ट का पूर्ण रूप क्या है?|पावर ऑन सेल्फ टेस्ट|पावर ऑन स्विच टेस्ट|प्रोग्राम ऑन सेल्फ टेस्ट|प्रोग्राम ऑन स्विच टेस्ट|A",
    "147|हार्ड डिस्क की गति मापी जाती है-|आरपीएम में|मेगाबाइट में|किलोबाइट में|गीगाबाइट में|A",
    "148|बाइनरी नंबर प्रणाली में कितने अंक होते हैं?|1|2|8|10|B",
    "149|ऑक्टल नंबर प्रणाली का आधार क्या है?|2|8|10|16|B",
    "150|हेक्साडेसिमल नंबर प्रणाली का आधार क्या है?|8|10|12|16|D",
    "151|'BIT' का अर्थ है-|बाइनरी इंफॉर्मेशन टर्म|बाइनरी डिजिट|बाइनरी इंटरनेट टास्क|बाइनरी इनपुट टास्क|B",
    "152|एक निबल कितने बिट्स के बराबर होता है?|2|4|8|16|B",
    "153|एक मेगाबाइट में कितने किलोबाइट होते हैं?|1000|1024|1050|1100|B",
    "154|एक गीगाबाइट बराबर है-|1024 बाइट्स|1024 किलोबाइट|1024 मेगाबाइट|1024 टेराबाइट|C",
    "155|डेटा की सबसे छोटी इकाई क्या है?|बिट|बाइट|निबल|वर्ड|A",
    "156|निम्नलिखित में से कौन सी माप की सबसे बड़ी इकाई है?|किलोबाइट|मेगाबाइट|गीगाबाइट|टेराबाइट|D"
]
for line in page68_lines:
    p = parse_pipe_line(line)
    if p:
        qnum = int(p[0])
        tid = page68_topic_map.get(qnum, 25)
        raw_questions.append((68, tid, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 69 - Geography/Hydrosphere -> 25
page69_lines = [
    "328|The term 'Hydrosphere' is used for which of the following?|All biological forms of the world|The entire water content of the world|Entire vegetation of the world|Solid parts of the earth|B",
    "329|A water-holding stratum of the earth's crust is called:|an aquifer|a lake|a river|an ocean|A",
    "330|The water bodies having maximum salinity are:|Lakes|Rivers|Oceans|Seas|A",
    "331|Which of the following describes the percentage of fresh water available for human consumption?|2.5%|0.003%|1.0%|None of these|B",
    "332|Which of the following represents a correct sequence in the hydrological cycle?|Evaporation, precipitation, condensation, runoff|Evaporation, condensation, precipitation, runoff|Condensation, evaporation, precipitation, runoff|Precipitation, condensation, evaporation, runoff|B",
    "333|The highest concentration of salt is found in which of the following?|Lake Van|Red Sea|Great Salt Lake|Dead Sea|A",
    "334|Which of the following is not a source of fresh water?|Ice caps|Groundwater|Rivers|Oceans|D",
    "335|The largest fresh water lake in the world is:|Lake Victoria|Lake Superior|Lake Baikal|Lake Erie|B",
    "336|The world's largest lake (by area) is:|Caspian Sea|Lake Superior|Lake Victoria|Lake Huron|A",
    "337|Which of the following is the deepest lake in the world?|Caspian Sea|Lake Superior|Lake Baikal|Lake Victoria|C",
    "338|Which lake is located between the USA and Canada?|Lake Baikal|Lake Superior|Lake Victoria|Lake Tanganyika|B",
    "339|The 'Sea of Galilee' is located in:|Jordan|Israel|Lebanon|Syria|B",
    "340|Which of the following lakes is also known as the 'Dead Sea'?|Lake Van|Lake Baikal|Lake Assal|Lake Eyre|C",
    "341|The Aral Sea is located between which two countries?|Kazakhstan and Uzbekistan|Kazakhstan and Turkmenistan|Uzbekistan and Turkmenistan|Russia and Kazakhstan|A",
    "342|Which of the following is the largest saline lake in India?|Chilika Lake|Pulicat Lake|Sambhar Lake|Wular Lake|C",
    "343|In which country is Lake Titicaca located?|Peru and Bolivia|Brazil and Argentina|Chile and Peru|Bolivia and Brazil|A",
    "344|Which is the largest lake in Africa?|Lake Tanganyika|Lake Malawi|Lake Victoria|Lake Turkana|C",
    "345|Which of the following is the world's highest navigable lake?|Lake Titicaca|Lake Baikal|Lake Superior|Lake Victoria|A",
    "346|The 'Finger Lakes' are located in which country?|Canada|USA|Australia|UK|B",
    "347|Great Bear Lake is located in:|USA|Canada|Russia|China|B"
]
for line in page69_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((69, 25, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 70 - Physics/Electricity -> 18
page70_lines = [
    "245|Two resistance wires are joined in parallel. Their resultant resistance is 6/5 Ohm. One of the wire is broken and the effective resistance becomes 2 Ohm. Then the resistance of the wire that was broken was|3/5 Ohm|2 Ohm|6/5 Ohm|3 Ohm|D",
    "246|Heat produced in a conductor of resistance R, when a current I flows through it for a time t is given by|I^2Rt|I R^2 t|I R t^2|I^2 R / t|A",
    "247|The equivalent resistance of a series combination of two resistances is 'S'. When they are joined in parallel, the total resistance is 'P'. If S=nP, then the minimum possible value of n is|4|3|2|1|A",
    "248|The equivalent resistance of the network shown in the figure between points A and B is|r|r/2|2r|3r/2|A",
    "249|A wire of resistance R is cut into 'n' equal parts. These parts are then connected in parallel. The equivalent resistance of the combination will be|nR|R/n|n/R|R/n^2|D",
    "250|A circuit has a fuse of 5 A. What is the maximum number of 100 W (220 V) bulbs that can be safely used in the circuit?|20|11|9|15|B",
    "251|Three resistors 2 Ohm, 3 Ohm and 5 Ohm are combined in parallel. What will be their equivalent resistance?|10 Ohm|30/31 Ohm|31/30 Ohm|None of these|B",
    "252|A current of 0.5 A is drawn by a filament of an electric bulb for 10 minutes. The amount of electric charge that flows through the circuit is|300 C|500 C|150 C|5 C|A"
]
for line in page70_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((70, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 71 - Physics/Light -> 18
page71_lines = [
    "152|The image formed by a concave mirror is observed to be virtual, erect and larger than the object. Where should be the position of the object?|Between the principal focus and the centre of curvature|At the centre of curvature|Beyond the centre of curvature|Between the pole of the mirror and its principal focus|D",
    "153|No matter how far you stand from a mirror, your image appears erect. The mirror is likely to be|plane|concave|convex|either plane or convex|D",
    "154|Which of the following mirrors is used by a dentist to examine a small cavity?|Convex mirror|Plane mirror|Concave mirror|Any of the above|C",
    "155|A concave mirror produces three times magnified (enlarged) real image of an object placed at 10 cm in front of it. Where is the image located?|30 cm|10 cm|-30 cm|40 cm|C",
    "156|The linear magnification produced by a convex mirror is always:|equal to 1|less than 1|more than 1|infinity|B",
    "157|Magnification produced by a rear view mirror fitted in vehicles:|is less than one|is more than one|is equal to one|can be more than or less than one depending upon the position of the object in front of it|A",
    "158|The path of a ray of light coming from air passing through a rectangular glass slab traced by four students are shown as A, B, C and D in figure. Which one of them is correct?|A|B|C|D|B",
    "159|You are given water, mustard oil, glycerine and kerosene. In which of these media, a ray of light incident obliquely at same angle would bend the most?|Kerosene|Water|Mustard oil|Glycerine|D",
    "160|Which of the following can make a parallel beam of light when light from a point source is incident on it?|Concave mirror as well as convex lens|Convex mirror as well as concave lens|Two plane mirrors placed at 90 degrees to each other|Concave mirror as well as concave lens|A",
    "161|A ray of light is travelling from a rarer medium to a denser medium. While entering the denser medium at the point of incidence, it|goes straight into the second medium|bends towards the normal|bends away from the normal|does not enter at all|B",
    "162|Light travels fastest in|Water|Air|Glass|Diamond|B",
    "163|The refractive index of transparent medium is greater than one because|Speed of light in vacuum < speed of light in medium|Speed of light in vacuum > speed of light in medium|Speed of light in vacuum = speed of light in medium|Frequency of light wave changes when it goes from rarer to denser medium|B",
    "164|The refractive index of water is 1.33. The speed of light in water will be|1.33 x 10^8 m/s|3 x 10^8 m/s|2.26 x 10^8 m/s|2.66 x 10^8 m/s|C",
    "165|The refractive index of glass is 1.5. The speed of light in glass is|2 x 10^8 m/s|2.25 x 10^8 m/s|3 x 10^8 m/s|2.5 x 10^8 m/s|A",
    "166|A light ray enters from medium A to medium B as shown in figure. The refractive index of medium B relative to A will be|greater than unity|less than unity|equal to unity|zero|A",
    "167|Beams of light are incident through the holes A and B and emerge out of box through the holes C and D respectively as shown in the figure. Which of the following could be inside the box?|A rectangular glass slab|A convex lens|A concave lens|A prism|A"
]
for line in page71_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((71, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 72 - Civil Engineering/Irrigation -> 18
page72_lines = [
    "172|The canal which is used for irrigation only on one side is:|Contour canal|Ridge canal|Side slope canal|Watershed canal|A",
    "173|The canal which is not used for irrigation is:|Main canal|Branch canal|Distributary|Water course|A",
    "174|The most suitable section for a canal is:|Rectangular|Trapezoidal|Circular|none of these|B",
    "175|A canal aligned approximately parallel to the contours of the country is:|Contour canal|Ridge canal|Side slope canal|Watershed canal|A",
    "176|The canal which is aligned along the ridge line is:|Ridge canal|Contour canal|Side slope canal|Watershed canal|A",
    "177|The canal which is aligned at right angles to the contours is:|Ridge canal|Contour canal|Side slope canal|Watershed canal|C",
    "178|The sensitivity of a rigid module is:|zero|0.5|1.0|2.0|A",
    "179|When the H.F.L. of the drain is sufficiently below the bottom of the canal trough, the cross-drainage work is called:|Aqueduct|Syphon aqueduct|Super passage|Syphon|A",
    "180|In a syphon aqueduct, the most critical condition occurs when:|Drain is full and canal is empty|Canal is full and drain is empty|Both are full|Both are empty|A",
    "181|The most suitable location of a canal head regulator is:|at 90 degrees to the weir axis|at 45 degrees to the weir axis|parallel to the weir axis|none of these|A",
    "182|A canal aligned approximately parallel to the natural drainage of the area is:|Contour canal|Ridge canal|Side slope canal|Watershed canal|C",
    "183|The silt factor in Lacey's theory is given by:|f = 1.76 sqrt(dm)|f = 1.76 dm|f = 1.76 (dm)^(1/3)|f = 1.56 sqrt(dm)|A",
    "184|The regime scour depth as per Lacey's theory is:|R = 0.47 (Q/f)^(1/3)|R = 1.35 (Q/f)^(1/3)|R = 1.2 (Q/f)^(1/3)|R = 0.47 (Qf)^(1/3)|A",
    "185|The perimeter P of a Lacey's regime channel for a discharge Q is:|P = 4.75 sqrt(Q)|P = 4.82 sqrt(Q)|P = 3.75 sqrt(Q)|P = 5.75 sqrt(Q)|A",
    "186|The side slopes of a regime channel as per Lacey's theory is:|1 : 1|1/2 : 1|1.5 : 1|2 : 1|B",
    "187|In Lacey's theory, the velocity of flow is proportional to:|Q^(1/6)|Q^(1/2)|Q^(1/3)|Q^(2/3)|A",
    "188|The bed slope of a regime channel is proportional to:|Q^(-1/6)|Q^(1/6)|Q^(-1/2)|Q^(1/2)|A",
    "189|A fall is provided in a canal when:|ground slope < bed slope|ground slope > bed slope|ground slope = bed slope|none of these|B",
    "190|The canal which can irrigate only on one side is:|Ridge canal|Contour canal|Side slope canal|Watershed canal|B",
    "191|For a discharge of 64 cumecs, the perimeter as per Lacey's theory is:|38 m|40 m|42 m|44 m|A",
    "192|In a regime channel, the silt is kept in suspension by:|vertical eddies|horizontal eddies|both (A) and (B)|none of these|A",
    "193|Side slope canal is:|aligned parallel to contours|aligned parallel to natural drainage|aligned along the ridge line|none of these|B",
    "194|In Kennedy's theory, the critical velocity ratio is:|V/Vo|Vo/V|V * Vo|V + Vo|A",
    "195|The silt factor in Lacey's theory depends upon:|size of silt particles|discharge|bed slope|all of these|A",
    "196|Kennedy's critical velocity Vo (m/sec) is given by:|Vo = 0.55 m y^0.64|Vo = 0.55 m y^0.5|Vo = 0.55 m y^0.6|none of these|A"
]
for line in page72_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((72, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 73 - Transformers/Electrical -> 18
page73_lines = [
    "354|The core of a transformer is laminated to reduce-|Eddy current loss|Hysteresis loss|Copper loss|Magnetic loss|A",
    "355|Efficiency of a transformer is maximum when-|Eddy current loss = Hysteresis loss|Iron loss = Copper loss|Copper loss = Hysteresis loss|Eddy current loss = Copper loss|B",
    "356|Function of transformer is to-|Convert AC to DC|Convert DC to AC|Step down or step up DC voltages|Step down or step up AC voltages|D",
    "357|What is the efficiency of a transformer as compared with that of electric motors of the same power?|Much higher|Much lower|Same|About 5 percent lower|A",
    "358|The power factor of a transformer at no load is approximately-|0.5 lagging|0.2 lagging|0.2 leading|0.5 leading|B",
    "359|A transformer is used to change the value of-|Voltage|Frequency|Power|Power factor|A",
    "360|In a transformer, the energy is conveyed from primary to secondary-|Through cooling medium|Through air|By the flux|None of these|C",
    "361|Laminated cores, in electrical machines, are used to reduce-|Copper loss|Eddy current loss|Hysteresis loss|All of these|B",
    "362|Transformer core is laminated to reduce-|Hysteresis loss|Eddy current loss|Both (a) and (b)|None of these|B",
    "363|The core of a transformer is laminated to-|Reduce hysteresis loss|Reduce eddy current loss|Reduce copper loss|Reduce reluctance of magnetic circuit|B",
    "364|A transformer does not possess ......... part.|Moving|Magnetic|Static|None of these|A",
    "365|For a transformer, the condition for maximum efficiency is-|Hysteresis loss = eddy current loss|Core loss = hysteresis loss|Copper loss = iron loss|Total loss = 2/3 copper loss|C",
    "366|If the supply frequency of a transformer increases, then the eddy current loss-|increases|decreases|remains constant|none of these|A",
    "367|Open circuit test in a transformer is performed with:|Rated transformer voltage|Rated transformer current|Direct current|High frequency supply|A",
    "368|Low voltage windings are placed near the core in the case of a concentric winding because:|It reduces insulation requirement|It reduces the amount of copper required|It reduces eddy current loss|It reduces hysteresis loss|A",
    "369|Power transformers are designed to have maximum efficiency at:|No load|Half load|Near full load|Little more than full load|C",
    "370|Short circuit test in a transformer is performed with:|Rated transformer voltage|Rated transformer current|Direct current|High frequency supply|B",
    "371|The hum in a transformer is mainly due to:|Magnetostriction|Mechanical vibrations|Load fluctuations|None of these|A",
    "372|While performing short circuit test on a transformer, the ......... winding is usually short-circuited.|Low voltage|High voltage|Any of the two|None of these|A",
    "373|Power transformers are generally designed to have maximum efficiency around:|No-load|Half-load|Full-load|10 percent overload|C",
    "374|A transformer-|Changes AC to DC|Changes DC to AC|Steps up or down DC voltages and current|Steps up or down AC voltages and current|D",
    "375|The transformation ratio of a transformer, when used for the purpose of impedance matching is:|n = Z2/Z1|n = (Z2/Z1)^2|n = sqrt(Z2/Z1)|n = sqrt(Z1/Z2)|C",
    "376|In an ideal transformer:|Winding resistances are negligible|Leakage flux is zero|Core losses are negligible|All of these|D",
    "377|For an ideal transformer:|Primary and secondary windings have no resistance|Core has infinite permeability|Core loss is zero|All of the above|D",
    "378|A transformer-|changes AC to DC|changes DC to AC|steps up or down DC voltages and current|steps up or down AC voltages and current|D",
    "379|In an ideal transformer:|Winding resistances are negligible|Leakage flux is zero|Core losses are negligible|All of these|D"
]
for line in page73_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((73, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 74 - Indian Polity -> 14
page74_lines = [
    "280|Match List I with List II: List I (System) (a) Unitary system (b) Federal system (c) Parliamentary system (d) Presidential system List II (Feature) (i) Separation of powers (ii) Concentration of powers (iii) Division of powers (iv) Close relationship between executive and legislature Codes: (a) (b) (c) (d)|(ii) (iii) (iv) (i)|(i) (ii) (iii) (iv)|(iii) (iv) (i) (ii)|(iv) (i) (ii) (iii)|A",
    "281|The Indian Constitution is:|Rigid|Flexible|Neither rigid nor flexible|Partly rigid and partly flexible|D",
    "282|The Preamble of the Indian Constitution was for the first time amended by the:|24th Amendment|42nd Amendment|44th Amendment|None of the above|B",
    "283|The mind of the makers of the Constitution of India is reflected in which of the following?|The Preamble|The Fundamental Rights|The Directive Principles of State Policy|The Fundamental Duties|A",
    "284|Which of the following is not a feature of the Indian Constitution?|Parliamentary Government|Presidential Government|Independence of Judiciary|Federal Government|B",
    "285|In which case the Supreme Court of India held that 'the Preamble is the part of the Constitution'?|Berubari Case|Keshvananda Bharti Case|S.R. Bommai Case|None of the above|B",
    "286|Which one of the following words was NOT included in the Preamble of the Indian Constitution in 1975?|Fraternity|Sovereign|Equality|Integrity|D",
    "287|'To uphold and protect the Sovereignty, Unity and Integrity of India' is a provision made in the:|Preamble of the Constitution|Directive Principles of State Policy|Fundamental Rights|Fundamental Duties|D",
    "288|The Preamble of the Indian Constitution was based on:|Objective Resolution|Nehru Report|Government of India Act, 1935|Indian Independence Act, 1947|A",
    "289|Which of the following is not a basic feature of the Indian Constitution?|Fundamental Rights|Independence of Judiciary|Presidential System of Government|Federalism|C"
]
for line in page74_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((74, 14, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 75 - Beams/Strength of Materials -> 18
page75_lines = [
    "355|Point of contra-flexure is the point where:|Bending moment is maximum|Bending moment is zero|Bending moment changes its sign|Shear force is maximum|C",
    "356|For a simply supported beam of span 'l' carrying a uniformly distributed load 'w' over the entire span, the maximum bending moment is:|wl/8|wl^2/8|wl^2/4|wl^2/12|B",
    "357|In a cantilever beam of length 'L' carrying a point load 'W' at the free end, the maximum bending moment is:|WL/4|WL/2|WL|WL^2/2|C",
    "358|The bending moment on a section is maximum where shear force:|is maximum|is zero or changes sign|is minimum|is zero|B",
    "359|A simply supported beam of length 'L' carries a point load 'W' at the centre. The maximum bending moment is:|WL/4|WL/2|WL/8|WL/12|A",
    "360|The rate of change of bending moment is equal to:|Shear force|Intensity of loading|Deflection|Slope|A",
    "361|The rate of change of shear force is equal to:|Bending moment|Intensity of loading|Deflection|Slope|B",
    "362|At the point of contra-flexure:|Bending moment is zero|Bending moment is maximum|Shear force is zero|Bending moment changes its sign|D",
    "363|In a cantilever beam of length 'L' carrying a uniformly distributed load 'w' over the entire length, the maximum shear force is:|wL|wL/2|wL^2/2|Zero|A",
    "364|In a cantilever beam of length 'L' carrying a uniformly distributed load 'w' over the entire length, the maximum bending moment is:|wL^2/2|wL^2/4|wL^2/8|wL^2/12|A",
    "365|A beam which is fixed at one end and free at the other is called:|Simply supported beam|Fixed beam|Cantilever beam|Overhanging beam|C",
    "366|A beam supported at its both ends is called:|Simply supported beam|Fixed beam|Cantilever beam|Continuous beam|A",
    "367|A beam extending beyond the supports is called:|Simply supported beam|Fixed beam|Overhanging beam|Continuous beam|C",
    "368|A beam supported on more than two supports is called:|Continuous beam|Fixed beam|Simply supported beam|Overhanging beam|A",
    "369|A beam supported at its both ends and fixed at its both ends is called:|Simply supported beam|Fixed beam|Cantilever beam|Continuous beam|B",
    "370|The shear force at the free end of a cantilever beam of length L carrying a point load W at the free end is:|W|W/2|Zero|2W|A",
    "371|The shear force at the fixed end of a cantilever beam of length L carrying a point load W at the free end is:|W|W/2|Zero|2W|A",
    "372|The maximum shear force in a simply supported beam of length L carrying a point load W at the centre is:|W/2|W|2W|W/4|A",
    "373|The maximum shear force in a simply supported beam of length L carrying a uniformly distributed load w over the entire span is:|wL/2|wL|wL^2/2|wL^2/8|A"
]
for line in page75_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((75, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 76 - Computer Fundamentals -> 25
page76_lines = [
    "233|Which component is used to store data in a computer system?|Monitor|Hard Disk|Keyboard|Mouse|B",
    "234|What does RAM stand for?|Read Access Memory|Random Access Memory|Rapid Access Memory|Remote Access Memory|B",
    "235|Which of the following is an input device?|Printer|Monitor|Scanner|Speaker|C",
    "236|Which of the following is an output device?|Keyboard|Mouse|Microphone|Monitor|D",
    "237|What is the full form of CPU?|Central Processing Unit|Control Processing Unit|Computer Personal Unit|Central Power Unit|A",
    "238|Which memory is known as volatile memory?|ROM|Hard Disk|RAM|Flash Drive|C",
    "239|What is the main function of the ALU?|Store data|Perform arithmetic and logic operations|Manage network connections|Generate graphics|B",
    "240|Which of the following is a permanent storage device?|RAM|Cache Memory|Hard Disk|Registers|C",
    "241|Which component is considered the 'brain' of the computer?|RAM|CPU|Motherboard|Power Supply|B",
    "242|What does GUI stand for?|General User Interface|Graphical User Interface|Global User Interface|Group User Interface|B"
]
for line in page76_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((76, 25, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 77 - Heat Transfer/Mechanical -> 18
page77_lines = [
    "576|In a shell and tube heat exchanger, baffles are provided on the shell side to-|improve heat transfer|provide support for tubes|prevent stagnation of shell side fluid|all of the above|D",
    "577|The LMTD for counter flow heat exchanger as compared to parallel flow heat exchanger is-|more|less|same|depends on other factors|A",
    "578|For a balanced counter flow heat exchanger (m_h C_ph = m_c C_pc), the LMTD is-|zero|delta T1|delta T1 = delta T2|(delta T1 + delta T2)/2|C",
    "579|Heat transfer takes place according to-|Zeroth law of thermodynamics|First law of thermodynamics|Second law of thermodynamics|Third law of thermodynamics|C",
    "580|The rate of heat flow through a hollow sphere of inner radius r1 and outer radius r2 is proportional to-|(r1 r2)/(r2 - r1)|(r2 - r1)/(r1 r2)|r1 r2|(r2 - r1)|A",
    "581|Thermal conductivity of solid metals ______ with rise in temperature.|increases|decreases|remains same|may increase or decrease|B",
    "582|Thermal conductivity of non-metallic amorphous solids ______ with decrease in temperature.|increases|decreases|remains same|may increase or decrease|B",
    "583|Thermal conductivity of water ______ with rise in temperature.|increases|decreases|remains same|first increases then decreases|D",
    "584|In heat transfer, Nusselt number is a ratio of-|convection to conduction|buoyancy to viscous force|inertial to viscous force|none of the above|A",
    "585|The value of Prandtl number for air is about-|0.1|0.7|7|15|B",
    "586|For which of the following substances, the thermal conductivity is lowest?|Water|Air|Ash|Snow|B",
    "587|The units of thermal diffusivity are-|m2/hr|m2/hr-C|kcal/m2-hr|kcal/m-hr-C|A",
    "588|Critical thickness of insulation for a cylinder is-|k/h|2k/h|h/k|h/2k|A",
    "589|The effectiveness of a heat exchanger is the ratio of-|actual heat transfer to maximum possible heat transfer|maximum possible heat transfer to actual heat transfer|actual heat transfer to minimum possible heat transfer|minimum possible heat transfer to actual heat transfer|A",
    "590|For a boiling liquid, the heat transfer coefficient-|is constant|increases with temperature difference|decreases with temperature difference|first increases then decreases with temperature difference|B"
]
for line in page77_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((77, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 78 - Economics -> 25
page78_lines = [
    "627|Which of the following is not a characteristic of perfectly competitive market?|Large number of buyers and sellers|Homogeneous product|Free entry and exit|Product differentiation|D",
    "628|Perfectly competitive firm's demand curve is :|Horizontal line|Vertical line|Downward sloping|Upward sloping|A",
    "629|In the short run, a firm under perfect competition will continue to produce as long as price is equal to or greater than :|AVC|AC|MC|AFC|A",
    "630|A firm's equilibrium under perfect competition is reached when :|MC = MR|MC curve cuts MR from below|Both (A) and (B)|None of the above|C",
    "631|In the long run, a perfectly competitive firm earns :|Super normal profit|Normal profit|Sub normal profit|None of these|B",
    "632|Monopoly means :|Single seller|Single buyer|Few sellers|Large number of sellers|A",
    "633|A monopolist is a :|Price taker|Price maker|Both (A) and (B)|None of these|B",
    "634|The demand curve of a monopolist is :|Downward sloping|Upward sloping|Horizontal|Vertical|A",
    "635|For a monopolist, marginal revenue is :|Less than average revenue|More than average revenue|Equal to average revenue|None of these|A",
    "636|Which of the following is a feature of monopoly?|Single seller|No close substitutes|Barriers to entry|All of the above|D",
    "637|Price discrimination is possible under :|Perfect competition|Monopoly|Both (A) and (B)|None of these|B",
    "638|A monopolist can maximize profit by producing where :|MR = MC|MC curve cuts MR from below|Both (A) and (B)|None of the above|C",
    "639|In the long run, a monopolist earns :|Super normal profit|Normal profit|Sub normal profit|None of these|A",
    "640|The AR curve of a monopolist is also known as :|Demand curve|Supply curve|Average cost curve|Marginal cost curve|A",
    "641|Monopolistic competition is a market structure with :|Large number of sellers|Product differentiation|Free entry and exit|All of the above|D",
    "642|The demand curve under monopolistic competition is :|More elastic than monopoly|Less elastic than monopoly|Perfectly elastic|Perfectly inelastic|A",
    "643|In the short run, a firm under monopolistic competition earns :|Super normal profit|Normal profit|Loss|All of the above|D",
    "644|In the long run, a firm under monopolistic competition earns :|Super normal profit|Normal profit|Loss|None of these|B",
    "645|Selling costs are an important feature of :|Perfect competition|Monopoly|Monopolistic competition|None of these|C",
    "646|Oligopoly is a market structure with :|Single seller|Two sellers|Few sellers|Large number of sellers|C",
    "647|Kinked demand curve is a feature of :|Monopoly|Oligopoly|Perfect competition|Monopolistic competition|B",
    "648|The concept of kinked demand curve was given by :|Paul Sweezy|Alfred Marshall|J.M. Keynes|Adam Smith|A",
    "649|Duopoly is a special case of :|Monopoly|Oligopoly|Perfect competition|Monopolistic competition|B",
    "650|Cartels are formed under :|Perfect competition|Monopoly|Oligopoly|None of these|C",
    "651|Collusive oligopoly is also known as :|Cartel|Price leadership|Both (A) and (B)|None of these|C",
    "652|Non-collusive oligopoly model was given by :|Cournot|Bertrand|Sweezy|All of the above|D"
]
for line in page78_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((78, 25, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 79 - DC Machines/Electrical -> 18
page79_lines = [
    "560|An 8-pole generator has 500 armature conductors and has a useful flux per pole of 0.05 Wb. What is the e.m.f. generated if it is lap connected and runs at 1200 rpm?|1000 V|500 V|250 V|200 V|B",
    "561|For the circuit shown in the figure, find the value of resistance R to be connected across AB, so that the maximum power is transferred to it.|2.67 Ohm|1 Ohm|4 Ohm|2 Ohm|A",
    "562|The function of dummy coils in a D.C. machine is to|Improve commutation|Reduce armature reaction|Maintain mechanical balance of the armature|Increase the induced e.m.f.|C",
    "563|Which of the following parts of a D.C. machine is made of laminated sheets of silicon steel?|Yoke|Armature core|Commutator|Shaft|B",
    "564|For a P-pole machine, the relation between electrical and mechanical degrees is|theta_e = P/2 theta_m|theta_e = 4/P theta_m|theta_e = theta_m|theta_e = 2/P theta_m|A",
    "565|The armature core of a D.C. machine is laminated to minimize|Hysteresis loss|Eddy current loss|Copper loss|Mechanical loss|B",
    "566|Commutator in D.C. generators is used for|Collecting of current|Reducing friction|Converting A.C. armature current into D.C.|Increasing voltage|C",
    "567|D.C. machine fractional pitch windings are used to|Improve commutation|Reduce copper in the winding|Increase the generated e.m.f.|Reduce the weight of the machine|A",
    "568|Lamination of armature core of a D.C. machine is used to reduce|Eddy current loss|Hysteresis loss|Copper loss|Friction loss|A",
    "569|Brushes in D.C. machine are usually made of|Carbon|Copper|Aluminium|Iron|A",
    "570|A simplex lap winding armature of a D.C. machine has number of parallel paths|Equal to the number of poles|Two|One|None of the above|A",
    "571|The direction of rotation of a D.C. series motor can be changed by|Interchanging the supply terminals|Interchanging the field terminals|Interchanging the armature terminals|Either (b) or (c)|D",
    "572|If the speed of a D.C. motor increases with load, it is|Series motor|Shunt motor|Cumulatively compounded motor|Differential compounded motor|D",
    "573|Wave winding is used in D.C. machines which are designed for|Low voltage and low current|High voltage and low current|Low voltage and high current|High voltage and high current|B",
    "574|The air gap between stator and armature of a D.C. machine is kept small to|Reduce armature reaction|Provide stronger magnetic field|Improve commutation|Reduce the noise|B",
    "575|For a given number of poles (P) and armature conductors (Z), which of the following winding will give the highest e.m.f.?|Lap winding|Wave winding|Same e.m.f. in both|None of the above|B",
    "576|The resistance of the armature of a D.C. machine is|Very small|Very large|Zero|Infinite|A",
    "577|In D.C. machine, the pole shoes are used to|Spread the magnetic flux uniformly|Support the field coils|Reduce the reluctance of the magnetic path|All of the above|D",
    "578|In a D.C. machine, the number of commutator segments is equal to|Number of armature conductors|Number of armature coils|Twice the number of armature coils|Half the number of armature coils|B",
    "579|The back e.m.f. (E_b) of a D.C. motor is|Always greater than the applied voltage (V)|Always less than the applied voltage (V)|Equal to the applied voltage (V)|None of the above|B"
]
for line in page79_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((79, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# Page 80 - Transformers (Hindi) -> 18
page80_lines = [
    "152|एक ट्रांसफार्मर में प्राथमिक और माध्यमिक पक्ष के बीच का कला अंतर क्या है?|0 degree|90 degree|180 degree|360 degree|C",
    "153|ट्रांसफार्मर का वोल्टेज रेगुलेशन तब ऋणात्मक होता है जब भार का पावर फैक्टर-|शून्य होता है|इकाई होता है|पश्चगामी होता है|अग्रगामी होता है|D",
    "154|यदि प्राथमिक वोल्टेज 220 V है, प्राथमिक वाइंडिंग के फेरों की संख्या 50 है और माध्यमिक वाइंडिंग के फेरों की संख्या 100 है, तो माध्यमिक वोल्टेज क्या होगा?|440 V|220 V|110 V|55 V|A",
    "155|एक ट्रांसफार्मर पर खुला परिपथ परीक्षण क्या निर्धारित करता है?|कोर लौह हानि|ताम्र हानि|घर्षण हानि|पूर्ण भार पर कुल हानि|A",
    "156|ट्रांसफार्मर के क्रोड को लैमिनेट किया जाता है-|केवल ताम्र हानि कम करने हेतु|केवल लौह हानि कम करने हेतु|केवल भंवर धारा हानि कम करने हेतु|शैथिल्य एवं भंवर धारा दोनों हानियों को कम करने हेतु|C",
    "157|एक वितरण ट्रांसफार्मर का भार सामान्यतः 24 घंटे बदलता रहता है। इस प्रकार के ट्रांसफार्मर को किसके लिए अभिकल्पित किया जाना चाहिए?|अधिकतम दक्षता|पूर्ण-दिवस दक्षता|न्यूनतम ताम्र हानि|न्यूनतम लौह हानि|B",
    "158|ट्रांसफार्मर के समांतर प्रचालन के लिए सबसे महत्वपूर्ण शर्त क्या है?|समान वोल्टेज अनुपात|समान kVA रेटिंग|समान प्रतिशत प्रतिबाधा|समान ध्रुवता|D"
]
for line in page80_lines:
    p = parse_pipe_line(line)
    if p:
        raw_questions.append((80, 18, p[0], p[1], p[2], p[3], p[4], p[5], p[6]))

# ===================== WRITE OUTPUT FILE =====================
output_path = '/tmp/batch3_questions.txt'

def esc(s):
    """Escape single quotes in a string."""
    return s.replace("'", "\\'")

with open(output_path, 'w', encoding='utf-8') as f:
    f.write("[\n")
    for i, (page, tid, qnum, qtext, optA, optB, optC, optD, correct) in enumerate(raw_questions):
        # Clean up option text (remove leading/trailing whitespace)
        qtext = qtext.strip()
        optA = optA.strip()
        optB = optB.strip()
        optC = optC.strip()
        optD = optD.strip()

        line = f"  ({tid}, '{esc(qtext)}', '{esc(optA)}', '{esc(optB)}', '{esc(optC)}', '{esc(optD)}', '{correct}', '', 'medium', 'yct-practice-set')"
        if i < len(raw_questions) - 1:
            line += ","
        line += "\n"
        f.write(line)
    f.write("]\n")

print(f"Total questions written: {len(raw_questions)}")
print(f"Output file: {output_path}")

# Count by page
from collections import Counter
page_counts = Counter(p[0] for p in raw_questions)
print("\nQuestions per page:")
for pg in sorted(page_counts.keys()):
    print(f"  Page {pg}: {page_counts[pg]} questions")

# Count by topic
topic_counts = Counter(p[1] for p in raw_questions)
print("\nQuestions per topic:")
topic_map_desc = {14: 'Polity', 18: 'General Science', 25: 'Computer Fundamentals', 26: 'Number Systems',
                  27: 'MS Office', 33: 'DBMS', 34: 'Operating Systems', 35: 'Networking', 37: 'Web Technologies',
                  38: 'SDLC/Management', 39: 'IoT/Emerging', 41: 'Computer Organization'}
for tid in sorted(topic_counts.keys()):
    desc = topic_map_desc.get(tid, f'Topic {tid}')
    print(f"  {desc} ({tid}): {topic_counts[tid]} questions")
