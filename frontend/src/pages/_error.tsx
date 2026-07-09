import Error from "next/error";

const CustomErrorComponent = (props: any) => {
  return <Error statusCode={props.statusCode} />;
};

CustomErrorComponent.getInitialProps = async (contextData: any) => {
  return Error.getInitialProps(contextData);
};

export default CustomErrorComponent;
