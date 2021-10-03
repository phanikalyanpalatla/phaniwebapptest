
from flask import Flask, request, render_template

import validators
from pymongo import MongoClient
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine,MetaData
import io
import os
import pandas as pd
from flask_wtf import FlaskForm as Form

from sqlalchemy.sql import text
import pymongo
import json
from wtforms import StringField,SelectField
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, String, Integer,Float




app = Flask(__name__)
app.config['SECRET_KEY']='phani'

with open('config.json') as f:
    cred = json.load(f)


#pg_connection=os.environ.get("DATABASE_URL")
pg_connection=cred["postgresql_connection"]
engine = create_engine(pg_connection)

db = declarative_base()



class orders(db):
    __tablename__='orders'
    id = Column(Integer,primary_key=True)
    created_at = Column(String)
    order_name = Column(String)
    customer_id = Column(String)
    expert_id = Column(Integer)

class deliveries(db):
    __tablename__='deliveries'
    id = Column(Integer,primary_key=True)
    order_item_id = Column(Integer)
    delivered_quantity = Column(Integer)

class order_items(db):
    __tablename__='order_items'
    id = Column(Integer,primary_key=True)
    order_id = Column(Integer)
    price_per_unit = Column(Float)
    quantity = Column(Integer)
    product = Column(String)

#db.create_all()

db.metadata.create_all(bind=engine)

def insert_posgre(df,input_for,engine):
    try:
        db.metadata.create_all(bind=engine)
        engine.connect().execute(text('TRUNCATE TABLE {0}'.format(input_for)).execution_options(autocommit=True))#.execution_options(autocommit=True)    
    except Exception as ex:
        print('truncate error',ex)

    df.to_sql(input_for,engine, if_exists='append',method='multi',index=False)

    '''
    #alternative insert
    df.head(0).to_sql(input_for, con=engine,if_exists='replace', index=False)
    raw_con = engine.raw_connection() 
    cur  = raw_con.cursor()
    out = io.StringIO()

    # write just the body of your dataframe to a csv-like file object
    df.to_csv(out, sep='\t', header=False, index=False) 

    out.seek(0) # sets the pointer on the file object to the first line
    contents = out.getvalue()
    cur.copy_from(out, input_for, null="") # copies the contents of the file object into the SQL cursor and sets null values to empty strings
    raw_con.commit()    
    '''

def insert_mongo_db(data,db_name,collection_name):
    with open('config.json') as f:
        cred = json.load(f)
    client = pymongo.MongoClient(cred["mongo_connection"])
    db = client[db_name]
    collection = db[collection_name]
    collection.drop()
    data_dict = data.to_dict('records')
    collection.insert_many(data_dict)


def query_mongodb(db_name,collection_name,type='df'):
    with open('config.json') as f:
        cred = json.load(f)
    client = pymongo.MongoClient(cred["mongo_connection"])
    db = client[db_name]
    collection = db[collection_name]
    if type=='df':
        data = pd.DataFrame(list(collection.find()))
        return data
    else:
        return list(collection.find())
def query_posgres(engine,table,db='db'):
    return pd.read_sql_query('select * from {0}'.format(table),con=engine)


def refresh_data(posgresengine,orders_table,deliveries_table,order_items_table,customers_collection,customer_companies_collection):
    orders = query_posgres(posgresengine,orders_table)
    deliveries = query_posgres(posgresengine,deliveries_table)
    order_items = query_posgres(posgresengine,order_items_table)
    customers= query_mongodb('db',customers_collection)  
    customer_companies=query_mongodb('db',customer_companies_collection)  

    result =pd.merge(orders.rename(columns={'id': 'order_id','created_at':'order_date'}), order_items.rename(columns={'id': 'order_item_id'}), on='order_id')

    result=pd.merge(result, deliveries.rename(columns={'id': 'delivery_id'}), on='order_item_id')


    result=pd.merge(result, customers.rename(columns={'user_id': 'customer_id','name':'customer_name'}), on='customer_id')


    result=pd.merge(result, customer_companies, on='company_id')
    result['delivery_amount']=result['delivered_quantity']*result['price_per_unit']

    
    result=(result[['order_name','company_name','customer_name','order_date','delivery_amount']])


    r2 = result.groupby(['order_name','company_name','customer_name','order_date']).agg({'delivery_amount':'sum'}).reset_index()

    insert_mongo_db(r2,'db','order_book')



table_names = ['orders','deliveries','order_items','customers','customer_companies']

class inputform(Form): 
    input_for=SelectField(u'Data type', choices=table_names)



@app.route('/upload', methods=['GET', 'POST'])
def upload():
    engine = create_engine(pg_connection)
    form = inputform()
    if request.method == 'POST':
        #if form.validate_on_submit():
        input_for=form.input_for.data 
        df=pd.read_csv(request.files.get('file'))
        if input_for not in ['customers','customer_companies']:
            if input_for=='orders':
                df['created_at']=pd.to_datetime(df['created_at'], format='%Y-%m-%dT%H:%M:%SZ')
                df['created_at'] = df['created_at'].dt.tz_localize('UTC')
                df['created_at'] = df['created_at'].dt.tz_convert('Australia/Sydney')
                df['created_at']=df['created_at'].dt.strftime("%b %d %Y, %I:%M %p")                      
                insert_posgre(df,input_for,engine)
            else:
                insert_posgre(df,input_for,engine)
        else:          
            insert_mongo_db(df,'db',input_for)
        refresh_data(engine,'orders','deliveries','order_items','customers','customer_companies')   

        return render_template('sucess.html',value=request.files['file'].filename)
    return render_template('input.html',form=form,title='File Upload Tool')

@app.route('/')
def index():
    return render_template('home.html', title='Home')

@app.route('/orders')
def orderbook():
    order_book = query_mongodb('db','order_book','tupple')
    return render_template('table.html', title='Order Book',
                           orders=order_book)

if __name__ == '__main__':
   app.run()